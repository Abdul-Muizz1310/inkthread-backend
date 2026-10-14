"""Spec 04 § 7-8 and the composed stage (T-LK-21…26)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from link_drafts import DraftBuilder, edges_of, evidence_fits

from inkthread.domain.link.build import link_rules
from inkthread.domain.model import EdgeType, EvidenceSide, NodeKind


def _doc() -> tuple[DraftBuilder, dict[str, str]]:
    b = DraftBuilder()
    ids = {n: b.section(f"{n} Heading {n}", n) for n in ("3", "4", "5")}
    b.current = b.section("6 Fees", "6")
    return b, ids


def test_t_lk_21_notwithstanding_overrides_on_source() -> None:
    b, ids = _doc()
    node = b.part("Notwithstanding Section 4, the fee is due.")
    link_rules(b.draft, b.sections)
    (edge,) = edges_of(b.draft, EdgeType.OVERRIDES)
    assert (edge.source, edge.target) == (node, ids["4"])
    assert edge.evidence_on is EvidenceSide.SOURCE
    assert edge.evidence is not None
    assert edge.evidence.quote == "Notwithstanding Section 4"
    assert edge.method == "R-PREC-notwithstanding"
    assert edges_of(b.draft, EdgeType.REFERS_TO) == []


def test_supersedes_overrides_on_source() -> None:
    b, ids = _doc()
    node = b.part("This schedule supersedes Section 3 in full.")
    link_rules(b.draft, b.sections)
    (edge,) = edges_of(b.draft, EdgeType.OVERRIDES)
    assert (edge.source, edge.target, edge.method) == (node, ids["3"], "R-PREC-supersedes")


def test_t_lk_22_except_as_provided_overrides_on_target() -> None:
    b, ids = _doc()
    node = b.part("Except as provided in Section 5, fees are final.")
    link_rules(b.draft, b.sections)
    (edge,) = edges_of(b.draft, EdgeType.OVERRIDES)
    assert (edge.source, edge.target) == (ids["5"], node)
    assert edge.evidence_on is EvidenceSide.TARGET
    assert edge.evidence is not None
    assert edge.evidence.quote == "Except as provided in Section 5"
    assert evidence_fits(b.draft, edge)


def test_unless_otherwise_overrides_on_target() -> None:
    b, ids = _doc()
    node = b.part("Fees are final unless otherwise stated in Section 5.")
    link_rules(b.draft, b.sections)
    (edge,) = edges_of(b.draft, EdgeType.OVERRIDES)
    assert (edge.source, edge.target, edge.method) == (ids["5"], node, "R-PREC-unless-otherwise")


def test_t_lk_23_subject_to_qualifies_and_consumes_the_ref() -> None:
    b, ids = _doc()
    node = b.part("Subject to Sections 3 and 4, the fee is due. See Section 5.")
    link_rules(b.draft, b.sections)
    qualifies = edges_of(b.draft, EdgeType.QUALIFIES)
    assert {(e.source, e.target) for e in qualifies} == {(ids["3"], node), (ids["4"], node)}
    assert all(e.evidence_on is EvidenceSide.TARGET for e in qualifies)
    assert all(evidence_fits(b.draft, e) for e in qualifies)
    refers = edges_of(b.draft, EdgeType.REFERS_TO)
    assert [(e.source, e.target) for e in refers] == [(node, ids["5"])]


def test_t_lk_24_cue_and_ref_in_different_sentences() -> None:
    b, ids = _doc()
    node = b.part("Notwithstanding the above, fees apply. See Section 4.")
    link_rules(b.draft, b.sections)
    assert edges_of(b.draft, EdgeType.OVERRIDES) == []
    (ref,) = edges_of(b.draft, EdgeType.REFERS_TO)
    assert (ref.source, ref.target) == (node, ids["4"])


def test_t_lk_25_leadin_governs_a_table() -> None:
    b, _ = _doc()
    lead = b.part("The fees are as follows:")
    table = b.table([["Fee", "Amount"], ["Filing", "$350"]])
    link_rules(b.draft, b.sections)
    (edge,) = edges_of(b.draft, EdgeType.GOVERNS)
    assert (edge.source, edge.target, edge.method) == (lead, table, "R-GOV-leadin")
    assert edge.evidence is not None
    assert edge.evidence.quote == "The fees are as follows:"


def test_t_lk_25_leadin_governs_a_run_of_list_items() -> None:
    b, _ = _doc()
    lead = b.part("Members must do this. The steps are as follows")
    items = [b.part(f"Item {i}.", NodeKind.LIST_ITEM, marker=f"{i}.") for i in range(3)]
    b.part("After the list.")
    b.part("Not in the run.", NodeKind.LIST_ITEM, marker="4.")
    link_rules(b.draft, b.sections)
    governs = edges_of(b.draft, EdgeType.GOVERNS)
    assert [(e.source, e.target) for e in governs] == [(lead, i) for i in items]
    assert governs[0].evidence is not None
    assert governs[0].evidence.quote == "The steps are as follows"


def test_t_lk_25_leadin_followed_by_paragraph_governs_nothing() -> None:
    b, _ = _doc()
    b.part("The fees are the following:")
    b.part("A paragraph.")
    b.table([["Fee", "Amount"], ["Filing", "$350"]])
    link_rules(b.draft, b.sections)
    assert edges_of(b.draft, EdgeType.GOVERNS) == []


def test_leadin_does_not_cross_sections() -> None:
    b, ids = _doc()
    b.part("The fees are as follows:")
    b.current = ids["5"]
    b.table([["Fee", "Amount"], ["Filing", "$350"]])
    link_rules(b.draft, b.sections)
    assert edges_of(b.draft, EdgeType.GOVERNS) == []


def test_link_rules_runs_every_resolver() -> None:
    b, ids = _doc()
    b.part('"Member" means a firm admitted under 37 CFR 1.27.')
    b.part("Each Member pays as set by Section 4.")
    link_rules(b.draft, b.sections)
    kinds = {e.type for e in b.draft.edges.values()}
    assert {
        EdgeType.DEFINES,
        EdgeType.USES_TERM,
        EdgeType.CITES_EXTERNAL,
        EdgeType.REFERS_TO,
    } <= kinds
    assert all(e.made_by.id == e.method for e in b.draft.edges.values())
    assert ids


_FRAGMENTS = st.sampled_from(
    [
        '"Member" means a firm.',
        "Each Member pays.",
        "Notwithstanding Section 4,",
        "Except as provided in Section 5,",
        "subject to Sections 3 and 4",
        "See Section 9.",
        "this Section 6",
        "under 37 CFR 1.27.",
        "Section 10(b) of the Securities Exchange Act",
        "the table below",
        "Table 1",
        "1.16(a)",
        "as follows:",
        "Artificial Intelligence (AI)",
        "the preceding list",
        "fees",
        ".",
        "“Fee” includes charges.",
        "https://example.com/x.",
    ]
)
_PART = st.tuples(
    st.lists(_FRAGMENTS, min_size=1, max_size=6),
    st.sampled_from([NodeKind.PARAGRAPH, NodeKind.LIST_ITEM, NodeKind.NOTE, NodeKind.DEFINITION]),
)


@settings(max_examples=60, deadline=None)
@given(st.lists(_PART, min_size=1, max_size=6), st.booleans())
def test_t_lk_26_every_edge_fits_and_never_loops(
    parts: list[tuple[list[str], NodeKind]], with_table: bool
) -> None:
    b, _ = _doc()
    b.part("Table 1: Rule fees")
    if with_table:
        b.table([["Rule", "Fee"], ["1.16(a)", "$350"], ["1.16(t)", "$80"]])
    for fragments, kind in parts:
        b.part(" ".join(fragments), kind, marker="1." if kind is NodeKind.LIST_ITEM else None)
    if with_table:
        b.table([["Item", "See"], ["Filing", "1.16(a)"]])
    link_rules(b.draft, b.sections)
    for edge in b.draft.edges.values():
        assert edge.source != edge.target
        assert evidence_fits(b.draft, edge)
    for node in b.draft.nodes.values():
        for entry in node.unresolved:
            assert entry.span is None or entry.span.fits(node.text)
