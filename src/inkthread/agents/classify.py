"""A-classify (spec 05 § 3): roles for the parts the rules left untyped."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from inkthread.agents.deps import AgentDeps, AgentReport, Tally
from inkthread.agents.parts import (
    agent_maker,
    chunks,
    cut,
    flag_truncated,
    flag_unavailable,
    ground,
    visible_text,
)
from inkthread.agents.prompts import load_prompt
from inkthread.agents.runner import run_task
from inkthread.core.config import LlmMode
from inkthread.domain.draft import GraphDraft, RoleDraft
from inkthread.domain.model import Actor, Basis, NodeKind, RejectedClaim, Role

STAGE = "classify_agent"
TASK_ID = "A-classify"
BATCH = 12  # 20 overflowed nemotron-3-super's output on NIST AI 100-1 (2026-10-14)
MAX_BATCHES = 3
TEXT_LIMIT = 1200
CLASSIFIABLE = frozenset(
    {NodeKind.PARAGRAPH, NodeKind.LIST_ITEM, NodeKind.NOTE, NodeKind.DEFINITION}
)


class _Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    quote: str


class _Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part: str
    roles: list[Role]
    evidence: list[_Evidence]


class ClassifyAnswer(BaseModel):
    """The validated shape of a classify answer (aliases are checked by grounding, not here)."""

    model_config = ConfigDict(extra="forbid")
    labels: list[_Label]


def classify_schema(aliases: Sequence[str]) -> dict[str, object]:
    """The JSON Schema sent to the model, with the batch's aliases as an enum."""
    roles = [r.value for r in Role]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["labels"],
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["part", "roles", "evidence"],
                    "properties": {
                        "part": {"type": "string", "enum": list(aliases)},
                        "roles": {"type": "array", "items": {"type": "string", "enum": roles}},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["role", "quote"],
                                "properties": {
                                    "role": {"type": "string", "enum": roles},
                                    "quote": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            }
        },
    }


async def classify_agent(
    draft: GraphDraft, residual: Sequence[str], deps: AgentDeps
) -> AgentReport:
    """Ask the producer for roles on the residual parts and keep only the grounded ones."""
    for nid in residual:
        if draft.node(nid).kind not in CLASSIFIABLE:
            msg = f"{nid} is a {draft.node(nid).kind.value}, which classify does not label"
            raise ValueError(msg)
    if deps.mode is LlmMode.OFF:
        return AgentReport(skipped_reason="disabled")
    tally = Tally()
    batches = chunks(list(residual), BATCH, MAX_BATCHES)
    prompt = load_prompt("classify")
    for index, batch in enumerate(batches):
        alias = {f"n{i}": nid for i, nid in enumerate(batch, start=1)}
        parts = []
        for a, nid in alias.items():
            node = draft.node(nid)
            text, truncated = cut(visible_text(node), TEXT_LIMIT)
            if truncated:
                flag_truncated(draft, nid, stage=STAGE)
            parts.append(
                {"id": a, "kind": node.kind.value, "section": _section(draft, nid), "text": text}
            )
        outcome = await run_task(
            prompt=prompt,
            answer_model=ClassifyAnswer,
            schema=classify_schema(list(alias)),
            payload={"parts": parts},
            cascade=deps.producer_cascade,
            deps=deps,
        )
        tally.calls += outcome.calls
        if outcome.status == "cached":
            tally.cached += 1
        if outcome.answer is None or outcome.served_model is None:
            tally.skipped = tally.skipped or outcome.reason
            if outcome.reason == "disabled":
                break
            if outcome.reason == "budget":
                flag_unavailable(draft, [n for b in batches[index:] for n in b], stage=STAGE)
                break
            if outcome.reason == "model_unavailable":
                flag_unavailable(draft, batch, stage=STAGE)
            continue
        _accept(
            draft,
            outcome.answer,
            alias=alias,
            served=outcome.served_model,
            key=outcome.request_key,
            tally=tally,
        )
    return tally.report()


def _section(draft: GraphDraft, nid: str) -> str:
    section = draft.node(nid).section
    if section is None:
        return ""
    node = draft.node(section)
    return node.text if node.kind is NodeKind.SECTION else ""


def _accept(
    draft: GraphDraft,
    answer: ClassifyAnswer,
    *,
    alias: dict[str, str],
    served: str,
    key: str,
    tally: Tally,
) -> None:
    maker = agent_maker(Actor.AGENT, TASK_ID, served, key)

    def reject(item: str, reason: str) -> None:
        draft.reject(
            RejectedClaim(task=TASK_ID, request_key=key, item=item, reason=reason),
            stage=STAGE,
            maker=maker,
        )
        tally.rejected += 1

    for label in answer.labels:
        nid = alias.get(label.part)
        if nid is None:
            reject(label.part, "unknown_id")
            continue
        node = draft.node(nid)
        for role in dict.fromkeys(label.roles):
            item = f"{nid}#{role.value}"
            if role in node.roles:
                reject(item, "already_assigned")
                continue
            quotes = [e.quote for e in label.evidence if e.role is role]
            if not quotes:
                reject(item, "no_evidence")
                continue
            span = next((s for s in (ground(node, q) for q in quotes) if s is not None), None)
            if span is None:
                reject(item, "quote_not_found")
                continue
            draft.add_role(
                nid,
                RoleDraft(role=role, evidence=span, made_by=maker, basis=Basis.SEMANTIC),
                stage=STAGE,
            )
            tally.accepted += 1
