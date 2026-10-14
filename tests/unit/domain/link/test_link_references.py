"""Spec 04 § 5-6: internal references and identifiers (T-LK-12…20)."""

from __future__ import annotations

from link_drafts import DraftBuilder, edges_of

from inkthread.domain.link.citations import link_citations
from inkthread.domain.link.identifiers import is_identifier, link_identifiers
from inkthread.domain.link.references import emit_references, link_references
from inkthread.domain.model import EdgeType, FlagCode, NodeKind


def _refs(b: DraftBuilder) -> None:
    refs = link_references(b.draft, b.sections)
    emit_references(b.draft, refs, consumed=set())


def _targets(b: DraftBuilder, source: str) -> list[tuple[str, str | None]]:
    return [
        (e.target, e.label) for e in edges_of(b.draft, EdgeType.REFERS_TO) if e.source == source
    ]


def _tree() -> tuple[DraftBuilder, dict[str, str]]:
    b = DraftBuilder()
    s4 = b.section("4 Fees", "4")
    ids = {"4": s4}
    for n in ("4.2", "4.3", "4.4"):
        ids[n] = b.section(f"{n} Item", n, parent=s4)
    ids["1.16"] = b.section("1.16 National fees", "1.16")
    ids["A"] = b.section("Appendix A Tables", "A", counter="appendix")
    b.current = ids["1.16"]
    return b, ids


def test_t_lk_12_single_list_and_range() -> None:
    b, ids = _tree()
    one = b.part("See Section 4.2 for details.")
    two = b.part("See Sections 4.2 and 4.3 for details.")
    rng = b.part("See Sections 4.2\u20134.4 for details.")
    _refs(b)
    assert _targets(b, one) == [(ids["4.2"], "4.2")]
    assert sorted(_targets(b, two)) == sorted([(ids["4.2"], "4.2"), (ids["4.3"], "4.3")])
    assert {t for t, _ in _targets(b, rng)} == {ids["4.2"], ids["4.3"], ids["4.4"]}
    (edge,) = [e for e in edges_of(b.draft, EdgeType.REFERS_TO) if e.source == one]
    assert edge.method == "R-REF-section"
    assert edge.evidence is not None
    assert edge.evidence.quote == "4.2"
    assert not edge.weak


def test_keyword_refs_resolve_by_their_counter() -> None:
    b, ids = _tree()
    node = b.part("Fees are listed in Appendix A and § 4.3.")
    _refs(b)
    assert sorted(_targets(b, node)) == sorted([(ids["A"], "A"), (ids["4.3"], "4.3")])


def test_t_lk_13_parenthetical_prefix_fallback() -> None:
    b, ids = _tree()
    node = b.part("As set by Section 1.16(a), the fee is due.")
    _refs(b)
    assert _targets(b, node) == [(ids["1.16"], "1.16(a)")]


def test_t_lk_14_ref_of_an_act_is_external() -> None:
    b = DraftBuilder()
    b.section("10 Other", "10")
    node = b.part("Reports under Section 10(b) of the Securities Exchange Act are due.")
    link_citations(b.draft)
    _refs(b)
    assert _targets(b, node) == []
    (cite,) = edges_of(b.draft, EdgeType.CITES_EXTERNAL)
    assert cite.source == node
    assert cite.label == "Section 10(b) of the Securities Exchange Act"
    assert cite.evidence is not None
    assert cite.evidence.quote == cite.label
    assert not b.draft.node(node).has_flag(FlagCode.REFERENCE_UNRESOLVED)


def test_t_lk_15_unresolved_reference_is_flagged() -> None:
    b, _ = _tree()
    node = b.part("See Section 9 for details.")
    _refs(b)
    draft_node = b.draft.node(node)
    assert draft_node.has_flag(FlagCode.REFERENCE_UNRESOLVED)
    (entry,) = draft_node.unresolved
    assert entry.kind == "reference"
    assert entry.text == "9"
    assert entry.span is not None
    assert entry.span.fits(draft_node.text)
    assert _targets(b, node) == []


def test_t_lk_16_this_section_is_skipped() -> None:
    b, ids = _tree()
    node = b.part("Fees under this Section 4.2 are final.", section=ids["4.2"])
    _refs(b)
    assert _targets(b, node) == []
    assert not b.draft.node(node).has_flag(FlagCode.REFERENCE_UNRESOLVED)


def test_t_lk_17_caption_reference() -> None:
    b = DraftBuilder()
    b.section("1 Fees", "1")
    user = b.part("Fees are listed in Table 3.")
    b.part("Table 3: Annual fees")
    table = b.table([["Fee", "Amount"], ["Filing", "$350"]])
    _refs(b)
    (edge,) = [e for e in edges_of(b.draft, EdgeType.REFERS_TO) if e.source == user]
    assert edge.target == table
    assert edge.method == "R-REF-caption"
    assert edge.label == "Table 3"


def test_caption_without_table_targets_the_caption() -> None:
    b = DraftBuilder()
    user = b.part("See Figure 2 for the curve.")
    caption = b.part("Figure 2: The curve")
    _refs(b)
    assert _targets(b, user) == [(caption, "Figure 2")]


def test_unresolved_caption_is_flagged() -> None:
    b = DraftBuilder()
    user = b.part("See Table 9 for fees.")
    _refs(b)
    assert b.draft.node(user).has_flag(FlagCode.REFERENCE_UNRESOLVED)


def test_t_lk_18_positional_reference_is_weak() -> None:
    b = DraftBuilder()
    b.section("1 Fees", "1")
    user = b.part("Fees are set out in the table below.")
    b.part("Filler one.")
    table = b.table([["Fee", "Amount"], ["Filing", "$350"]])
    _refs(b)
    (edge,) = edges_of(b.draft, EdgeType.REFERS_TO)
    assert (edge.source, edge.target) == (user, table)
    assert edge.method == "R-REF-positional"
    assert edge.weak


def test_t_lk_18_positional_miss_adds_nothing() -> None:
    b = DraftBuilder()
    b.section("1 Fees", "1")
    user = b.part("Fees are set out in the following table.")
    for i in range(4):
        b.part(f"Filler {i}.")
    b.table([["Fee", "Amount"], ["Filing", "$350"]])
    _refs(b)
    assert edges_of(b.draft, EdgeType.REFERS_TO) == []
    assert not b.draft.node(user).has_flag(FlagCode.REFERENCE_UNRESOLVED)


def test_positional_preceding_list_targets_a_list_item() -> None:
    b = DraftBuilder()
    item = b.part("Submit the form.", NodeKind.LIST_ITEM, marker="1.")
    user = b.part("The preceding list is complete.")
    _refs(b)
    assert _targets(b, user) == [(item, "The preceding list")]


def _key_table(b: DraftBuilder) -> str:
    return b.table(
        [["Rule", "Fee"], ["1.16(a)", "$350"], ["1.16(t)", "$1,234.56"], ["1.17(b)", "$80"]]
    )


def test_t_lk_19_identifier_in_a_paragraph_refers_to_its_table() -> None:
    b = DraftBuilder()
    table = _key_table(b)
    user = b.part("The fee under 1.16(t) is due.")
    link_identifiers(b.draft)
    (edge,) = edges_of(b.draft, EdgeType.REFERS_TO)
    assert (edge.source, edge.target, edge.label) == (user, table, "1.16(t)")
    assert edge.method == "R-REF-identifier"
    assert edge.evidence is not None
    assert edge.evidence.quote == "1.16(t)"


def test_identifier_in_another_table_cell_carries_an_anchor() -> None:
    b = DraftBuilder()
    table = _key_table(b)
    other = b.table([["Item", "See"], ["Filing", "1.17(b)"]])
    link_identifiers(b.draft)
    (edge,) = edges_of(b.draft, EdgeType.REFERS_TO)
    assert (edge.source, edge.target) == (other, table)
    assert edge.anchor is not None
    assert (edge.anchor.row, edge.anchor.col) == (1, 1)


def test_t_lk_20_money_integers_and_self_make_no_identifier_edge() -> None:
    assert not is_identifier("1,234.56")
    assert not is_identifier("$350")
    assert not is_identifier("2024")
    assert not is_identifier("a-very-long-identifier-1")
    assert is_identifier("1.16(a)")
    assert is_identifier("FC-12")
    b = DraftBuilder()
    _key_table(b)
    b.part("A fee of 1,234.56 is due in 2024.")
    link_identifiers(b.draft)
    assert edges_of(b.draft, EdgeType.REFERS_TO) == []


def test_money_column_is_not_a_key_column() -> None:
    b = DraftBuilder()
    b.table([["Amount", "Fee"], ["1,234.56", "x"], ["2,000.00", "y"]])
    b.part("Pay 1,234.56 now.")
    link_identifiers(b.draft)
    assert edges_of(b.draft, EdgeType.REFERS_TO) == []
