"""Helpers the agent stages share: model-safe text, grounding, flags and makers."""

from __future__ import annotations

from collections.abc import Iterable

from inkthread.agents.grounding import snap
from inkthread.domain.draft import GraphDraft, NodeDraft
from inkthread.domain.model import Actor, Flag, FlagCode, Maker, Span

FLAG_MAKER = Maker(actor=Actor.RULE, id="R-INK-flags")


def visible_text(node: NodeDraft) -> str:
    """The node's text with its hidden spans removed: the only text a prompt may carry."""
    if not node.hidden_spans:
        return node.text
    out: list[str] = []
    cursor = 0
    for span in sorted(node.hidden_spans, key=lambda s: s.start):
        if span.start > cursor:
            out.append(node.text[cursor : span.start])
        cursor = max(cursor, span.end)
    out.append(node.text[cursor:])
    return "".join(out)


def cut(text: str, limit: int) -> tuple[str, bool]:
    """`text` cut to `limit` characters, and whether it was cut."""
    return (text[:limit], True) if len(text) > limit else (text, False)


def ground(node: NodeDraft, quote: str) -> Span | None:
    """Snap `quote` into the node's original text; a span touching hidden words does not count."""
    span = snap(node.text, quote)
    if span is None:
        return None
    if any(h.start < span.end and span.start < h.end for h in node.hidden_spans):
        return None
    return span


def agent_maker(actor: Actor, task_id: str, model: str, request_key: str) -> Maker:
    """The maker of a model-made element."""
    return Maker(actor=actor, id=task_id, model=model, request_key=request_key)


def flag_unavailable(draft: GraphDraft, node_ids: Iterable[str], *, stage: str) -> None:
    """Mark parts a skipped batch would have judged."""
    for nid in node_ids:
        draft.add_flag(nid, Flag(code=FlagCode.MODEL_UNAVAILABLE), stage=stage, maker=FLAG_MAKER)


def flag_truncated(draft: GraphDraft, node_id: str, *, stage: str) -> None:
    """Mark a part whose text was cut before it reached a model."""
    draft.add_flag(node_id, Flag(code=FlagCode.TRUNCATED_FOR_MODEL), stage=stage, maker=FLAG_MAKER)


def chunks[T](items: list[T], size: int, limit: int) -> list[list[T]]:
    """At most `limit` batches of at most `size` items each, in order."""
    return [items[i : i + size] for i in range(0, min(len(items), size * limit), size)]
