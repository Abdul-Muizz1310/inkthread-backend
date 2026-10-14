"""Spec 07 § 3: the small sketches the event stream sends."""

from __future__ import annotations

from finalize_sample import sample

from inkthread.domain.draft import GraphDraft
from inkthread.domain.sketches import SketchBatch, sketch


def test_sketch_of_a_delta() -> None:
    s = sample()
    batch = sketch(s.draft.take_delta(), "structure")
    assert isinstance(batch, SketchBatch)
    assert batch.stage == "structure"
    assert [n.id for n in batch.nodes] == list(s.draft.nodes)
    doc = batch.nodes[0]
    assert (doc.kind, doc.page, doc.depth, doc.order, doc.section) == (
        "document",
        None,
        0,
        0,
        None,
    )
    p1 = next(n for n in batch.nodes if n.id == s.p1)
    assert (p1.page, p1.section, p1.label) == (1, s.section, s.draft.node(s.p1).text)
    agent = next(e for e in batch.edges if e.id == s.agent_edge)
    assert (agent.type, agent.basis, agent.source, agent.target) == (
        "qualifies",
        "semantic",
        s.p2,
        s.p1,
    )
    assert {(r.node, r.role, r.basis) for r in batch.roles} == {
        (s.p1, "obligation", "explicit"),
        (s.p2, "definition", "semantic"),
    }
    assert [(f.node, f.code) for f in batch.flags] == [(s.p1, "note_not_found")]
    assert batch.model_dump(mode="json")["nodes"][0]["kind"] == "document"


def test_long_labels_are_cut() -> None:
    s = sample()
    s.draft.node(s.p2).text = "word " * 40
    s.draft.take_delta()
    d = GraphDraft(sha256="a" * 64, pipeline_version="1")
    d.add_node(s.draft.node(s.p2), stage="x")
    batch = sketch(d.take_delta(), "x")
    assert len(batch.nodes[0].label) <= 80
    assert batch.edges == ()
    assert batch.roles == ()
    assert batch.flags == ()
