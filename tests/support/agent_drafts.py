"""Small drafts and agent dependencies for the agent tests."""

from __future__ import annotations

from collections.abc import Sequence

from fake_llm import MemoryCallLog, MemoryStore, ScriptedModel

from inkthread.agents.deps import AgentDeps
from inkthread.core.config import LlmMode
from inkthread.domain.draft import GraphDraft, NodeDraft, RoleDraft
from inkthread.domain.model import Actor, Basis, Maker, NodeKind, Region, Role, Span

RULE = Maker(actor=Actor.RULE, id="R-SEC-part")
DOC = "d:aaaaaaaaaaaaaaaa"
SEC = "s:fees"
PRODUCER = ("p/primary:free", "f/fallback:free")
VERIFIER = ("v/fast:free", "f/fallback:free")


def draft(*parts: tuple[str, NodeKind, str], hidden: dict[str, Span] | None = None) -> GraphDraft:
    """A document with one section, "Fees", holding the given parts in order."""
    d = GraphDraft(sha256="a" * 64, pipeline_version="0.1.0")
    d.add_node(
        NodeDraft(
            id=DOC,
            kind=NodeKind.DOCUMENT,
            text="",
            order=0,
            section=None,
            depth=0,
            regions=[],
            made_by=RULE,
        ),
        stage="structure",
    )
    d.add_node(
        NodeDraft(
            id=SEC,
            kind=NodeKind.SECTION,
            text="Fees",
            order=1,
            section=DOC,
            depth=1,
            regions=[Region(page=1, bbox=(0, 0, 1, 1))],
            made_by=RULE,
        ),
        stage="structure",
    )
    for i, (nid, kind, text) in enumerate(parts, start=2):
        node = NodeDraft(
            id=nid,
            kind=kind,
            text=text,
            order=i,
            section=SEC,
            depth=2,
            regions=[Region(page=1, bbox=(0, 0, 1, 1))],
            made_by=RULE,
        )
        if hidden and nid in hidden:
            node.hidden_spans.append(hidden[nid])
        d.add_node(node, stage="structure")
    return d


def rule_role(d: GraphDraft, nid: str, role: Role, cue: str, *, weak: bool = False) -> None:
    """Give a node a rule-made role whose evidence is `cue`."""
    text = d.node(nid).text
    start = text.index(cue)
    d.add_role(
        nid,
        RoleDraft(
            role=role,
            evidence=Span.of(text, start, start + len(cue)),
            made_by=Maker(actor=Actor.RULE, id=f"R-ROLE-{role.value}"),
            basis=Basis.EXPLICIT,
            weak=weak,
        ),
        stage="classify_rules",
    )


def deps(
    model: ScriptedModel,
    *,
    mode: LlmMode = LlmMode.LIVE,
    store: MemoryStore | None = None,
    log: MemoryCallLog | None = None,
) -> AgentDeps:
    return AgentDeps(
        model=model,
        store=store or MemoryStore(),
        log=log or MemoryCallLog(),
        mode=mode,
        producer_cascade=PRODUCER,
        verifier_cascade=VERIFIER,
    )


def ids(n: int, prefix: str = "p:") -> Sequence[str]:
    return [f"{prefix}{i}" for i in range(1, n + 1)]
