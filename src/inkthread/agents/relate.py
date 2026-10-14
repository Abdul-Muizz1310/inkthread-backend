"""A-relate (spec 05 § 3): logic edges the text implies but does not spell out."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

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
from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.model import (
    LOGIC_TYPES,
    PART_KINDS,
    Actor,
    Basis,
    EdgeType,
    NodeKind,
    RejectedClaim,
    Role,
)

STAGE = "relate_agent"
TASK_ID = "A-relate"
BATCH = 6
MAX_BATCHES = 3
CANDIDATES = 8
FOCUS_LIMIT = 1200
CANDIDATE_LIMIT = 400

ALLOWED: Mapping[Role, tuple[EdgeType, ...]] = {
    Role.CONDITION: (EdgeType.QUALIFIES,),
    Role.COMPUTATION: (EdgeType.QUALIFIES,),
    Role.METHOD: (EdgeType.QUALIFIES,),
    Role.TEMPORAL: (EdgeType.QUALIFIES,),
    Role.EXCEPTION: (EdgeType.QUALIFIES, EdgeType.OVERRIDES),
    Role.SCOPE: (EdgeType.GOVERNS,),
    Role.EXAMPLE: (EdgeType.ILLUSTRATES,),
}
_EDGE_ORDER = list(EdgeType)
LOGIC_TYPES_ORDERED = [t for t in EdgeType if t in LOGIC_TYPES]

LogicType = Literal["governs", "qualifies", "overrides", "illustrates"]


class _Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: str
    type: LogicType
    target: str
    evidence: str


class RelateAnswer(BaseModel):
    """The validated shape of a relate answer."""

    model_config = ConfigDict(extra="forbid")
    relations: list[_Relation]


def relate_schema(focus: Sequence[str], aliases: Sequence[str]) -> dict[str, object]:
    """The JSON Schema sent to the model, with the batch's aliases as enums."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["relations"],
        "properties": {
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["focus", "type", "target", "evidence"],
                    "properties": {
                        "focus": {"type": "string", "enum": list(focus)},
                        "type": {"type": "string", "enum": [t.value for t in LOGIC_TYPES_ORDERED]},
                        "target": {"type": "string", "enum": list(aliases)},
                        "evidence": {"type": "string"},
                    },
                },
            }
        },
    }


def allowed_types(node: NodeDraft) -> list[EdgeType]:
    """Logic edge types the node's roles allow it to originate, in edge-type order."""
    allowed = {t for role in node.roles for t in ALLOWED.get(role, ())}
    return sorted(allowed, key=_EDGE_ORDER.index)


def focus_parts(draft: GraphDraft) -> list[NodeDraft]:
    """Content parts with a focus role and no outgoing logic edge; strong cues first."""
    has_logic = {e.source for e in draft.edges.values() if e.type in LOGIC_TYPES}
    found = [
        n
        for n in draft.nodes_of(*PART_KINDS)
        if n.id not in has_logic and any(r in ALLOWED for r in n.roles)
    ]

    def strong(n: NodeDraft) -> bool:
        return any(not d.weak for r, d in n.roles.items() if r in ALLOWED)

    return sorted(found, key=lambda n: (not strong(n), n.order))


def candidates(draft: GraphDraft, focus: NodeDraft) -> list[NodeDraft]:
    """Up to 8 content parts of the focus's section, nearest first, tables before the rest."""
    same = [n for n in draft.nodes_of(*PART_KINDS) if n.section == focus.section]
    at = next(i for i, n in enumerate(same) if n.id == focus.id)
    others = [(abs(i - at), i, n) for i, n in enumerate(same) if n.id != focus.id]
    others.sort(key=lambda t: (t[2].kind is not NodeKind.TABLE, t[0], t[1]))
    return [n for _, _, n in others[:CANDIDATES]]


async def relate_agent(draft: GraphDraft, deps: AgentDeps) -> AgentReport:
    """Ask the producer what each focus part qualifies, governs, overrides or illustrates."""
    if deps.mode is LlmMode.OFF:
        return AgentReport(skipped_reason="disabled")
    tally = Tally()
    batches = chunks(focus_parts(draft), BATCH, MAX_BATCHES)
    prompt = load_prompt("relate")
    for index, batch in enumerate(batches):
        alias: dict[str, str] = {}

        def name(nid: str, alias: dict[str, str] = alias) -> str:
            for a, n in alias.items():
                if n == nid:
                    return a
            a = f"c{len(alias) + 1}"
            alias[a] = nid
            return a

        offered: dict[str, list[str]] = {}
        texts: dict[str, str] = {}
        focus_items = []
        for focus in batch:
            fa = name(focus.id)
            text, truncated = cut(visible_text(focus), FOCUS_LIMIT)
            if truncated:
                flag_truncated(draft, focus.id, stage=STAGE)
            texts[fa] = text
            cands = [name(c.id) for c in candidates(draft, focus)]
            offered[fa] = cands
            focus_items.append(
                {
                    "id": fa,
                    "roles": [r.value for r in focus.roles if r in ALLOWED],
                    "allowed": [t.value for t in allowed_types(focus)],
                    "candidates": cands,
                }
            )
        for a, nid in alias.items():
            if a not in texts:
                texts[a] = cut(visible_text(draft.node(nid)), CANDIDATE_LIMIT)[0]
        nodes = [
            {"id": a, "kind": draft.node(nid).kind.value, "text": texts[a]}
            for a, nid in alias.items()
        ]
        outcome = await run_task(
            prompt=prompt,
            answer_model=RelateAnswer,
            schema=relate_schema(list(offered), list(alias)),
            payload={"nodes": nodes, "focus": focus_items},
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
                flag_unavailable(draft, [n.id for b in batches[index:] for n in b], stage=STAGE)
                break
            if outcome.reason == "model_unavailable":
                flag_unavailable(draft, [n.id for n in batch], stage=STAGE)
            continue
        _accept(
            draft,
            outcome.answer,
            alias=alias,
            offered=offered,
            served=outcome.served_model,
            key=outcome.request_key,
            tally=tally,
        )
    return tally.report()


def _accept(
    draft: GraphDraft,
    answer: RelateAnswer,
    *,
    alias: Mapping[str, str],
    offered: Mapping[str, list[str]],
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

    for rel in answer.relations:
        item = f"{rel.focus}-{rel.type}->{rel.target}"
        if rel.focus not in offered:
            reject(item, "unknown_id")
            continue
        source = draft.node(alias[rel.focus])
        if rel.target == rel.focus:
            reject(f"{source.id}-{rel.type}->{source.id}", "self_loop")
            continue
        if rel.target not in offered[rel.focus]:
            reject(item, "unknown_id")
            continue
        target = alias[rel.target]
        edge_type = EdgeType(rel.type)
        item = f"{source.id}-{edge_type.value}->{target}"
        if edge_type not in allowed_types(source):
            reject(item, "type_not_allowed")
            continue
        if not rel.evidence.strip():
            reject(item, "no_evidence")
            continue
        span = ground(source, rel.evidence)
        if span is None:
            reject(item, "quote_not_found")
            continue
        if any(
            (e.type, e.source, e.target) == (edge_type, source.id, target)
            for e in draft.edges.values()
        ):
            reject(item, "duplicate")
            continue
        draft.add_edge(
            EdgeDraft(
                type=edge_type,
                source=source.id,
                target=target,
                basis=Basis.SEMANTIC,
                method=TASK_ID,
                made_by=maker,
                evidence=span,
            ),
            stage=STAGE,
        )
        tally.accepted += 1
