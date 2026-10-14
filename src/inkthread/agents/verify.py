"""A-verify (spec 05 § 3): a second model's verdict on each semantic claim of this job."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from inkthread.agents.deps import AgentDeps, AgentReport, Tally
from inkthread.agents.parts import agent_maker, chunks, cut, visible_text
from inkthread.agents.prompts import load_prompt
from inkthread.agents.runner import run_task
from inkthread.core.config import LlmMode
from inkthread.domain.draft import GraphDraft
from inkthread.domain.model import (
    ROLE_ORDER,
    Actor,
    Basis,
    Flag,
    FlagCode,
    Maker,
    Role,
    Verdict,
)

STAGE = "verify_agent"
TASK_ID = "A-verify"
BATCH = 30
MAX_BATCHES = 2
TEXT_LIMIT = 600

VerdictValue = Literal["supported", "unsupported", "abstain"]


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str
    verdict: VerdictValue


class VerifyAnswer(BaseModel):
    """The validated shape of a verify answer."""

    model_config = ConfigDict(extra="forbid")
    verdicts: list[_Verdict]


def verify_schema(aliases: Sequence[str]) -> dict[str, object]:
    """The JSON Schema sent to the verifier, with the batch's claim aliases as an enum."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdicts"],
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim", "verdict"],
                    "properties": {
                        "claim": {"type": "string", "enum": list(aliases)},
                        "verdict": {
                            "type": "string",
                            "enum": ["supported", "unsupported", "abstain"],
                        },
                    },
                },
            }
        },
    }


@dataclass(frozen=True)
class Claim:
    """One semantic element to judge: an edge (by id) or a role (node id + role)."""

    made_by: Maker
    edge_id: str | None = None
    node_id: str | None = None
    role: Role | None = None


def claims_of(draft: GraphDraft) -> list[Claim]:
    """Every semantic edge, then every semantic role, each in reading order."""
    order = {nid: n.order for nid, n in draft.nodes.items()}
    edges = sorted(
        (e for e in draft.edges.values() if e.basis is Basis.SEMANTIC),
        key=lambda e: (order[e.source], order[e.target], e.id),
    )
    roles = [
        (n, r, d)
        for n in sorted(draft.nodes.values(), key=lambda n: n.order)
        for r, d in sorted(n.roles.items(), key=lambda rd: ROLE_ORDER[rd[0]])
        if d.basis is Basis.SEMANTIC
    ]
    return [Claim(made_by=e.made_by, edge_id=e.id) for e in edges] + [
        Claim(made_by=d.made_by, node_id=n.id, role=r) for n, r, d in roles
    ]


def _item(draft: GraphDraft, alias: str, claim: Claim) -> dict[str, str]:
    if claim.edge_id is not None:
        edge = draft.edges[claim.edge_id]
        quote = edge.evidence.quote if edge.evidence is not None else ""
        return {
            "id": alias,
            "kind": "edge",
            "type": edge.type.value,
            "source_text": cut(visible_text(draft.node(edge.source)), TEXT_LIMIT)[0],
            "target_text": cut(visible_text(draft.node(edge.target)), TEXT_LIMIT)[0],
            "quote": quote,
        }
    if claim.node_id is None or claim.role is None:
        msg = "a claim is an edge or a role"
        raise ValueError(msg)
    node = draft.node(claim.node_id)
    evidence = node.roles[claim.role].evidence
    return {
        "id": alias,
        "kind": "role",
        "role": claim.role.value,
        "part_text": cut(visible_text(node), TEXT_LIMIT)[0],
        "quote": evidence.quote if evidence is not None else "",
    }


async def verify_agent(draft: GraphDraft, deps: AgentDeps) -> AgentReport:
    """Ask the verifier about each claim; attach independent verdicts, flag the unsupported."""
    if deps.mode is LlmMode.OFF:
        return AgentReport(skipped_reason="disabled")
    tally = Tally()
    prompt = load_prompt("verify")
    for batch in chunks(claims_of(draft), BATCH, MAX_BATCHES):
        alias = {f"k{i}": c for i, c in enumerate(batch, start=1)}
        outcome = await run_task(
            prompt=prompt,
            answer_model=VerifyAnswer,
            schema=verify_schema(list(alias)),
            payload={"claims": [_item(draft, a, c) for a, c in alias.items()]},
            cascade=deps.verifier_cascade,
            deps=deps,
        )
        tally.calls += outcome.calls
        if outcome.status == "cached":
            tally.cached += 1
        if outcome.answer is None or outcome.served_model is None:
            tally.skipped = tally.skipped or outcome.reason
            if outcome.reason in {"disabled", "budget"}:
                break
            continue
        served, key = outcome.served_model, outcome.request_key
        given: dict[str, VerdictValue] = {}
        for v in outcome.answer.verdicts:
            given.setdefault(v.claim, v.verdict)
        maker = agent_maker(Actor.VERIFIER, TASK_ID, served, key)
        for a, claim in alias.items():
            if claim.made_by.model == served:
                tally.rejected += 1  # not independent: the claim keeps verifier_unavailable
                continue
            verdict = Verdict(verdict=given.get(a, "abstain"), model=served, request_key=key)
            _attach(draft, claim, verdict, maker)
            tally.accepted += 1
    return tally.report()


def _attach(draft: GraphDraft, claim: Claim, verdict: Verdict, maker: Maker) -> None:
    contested = Flag(code=FlagCode.CONTESTED)
    if claim.edge_id is not None:
        draft.set_edge_verdict(claim.edge_id, verdict, stage=STAGE, maker=maker)
        edge = draft.edges[claim.edge_id]
        if verdict.verdict == "unsupported" and contested not in edge.flags:
            # The draft has no edge-flag method; the verdict op above accounts for this flag.
            edge.flags.append(contested)
        return
    if claim.node_id is None or claim.role is None:
        msg = "a claim is an edge or a role"
        raise ValueError(msg)
    draft.set_role_verdict(claim.node_id, claim.role, verdict, stage=STAGE, maker=maker)
    if verdict.verdict == "unsupported":
        draft.add_flag(
            claim.node_id,
            Flag(code=FlagCode.CONTESTED, detail=claim.role.value),
            stage=STAGE,
            maker=maker,
        )
