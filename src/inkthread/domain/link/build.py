"""The `link_rules` stage: every deterministic resolver, in spec 04's order."""

from __future__ import annotations

from inkthread.domain.draft import GraphDraft
from inkthread.domain.link.citations import link_citations
from inkthread.domain.link.identifiers import link_identifiers
from inkthread.domain.link.leadins import link_leadins
from inkthread.domain.link.precedence import link_precedence
from inkthread.domain.link.references import emit_references, link_references
from inkthread.domain.link.terms import link_terms
from inkthread.domain.structure.types import SectionIndex


def link_rules(draft: GraphDraft, sections: SectionIndex) -> None:
    """Terms, citations, references, identifiers, precedence, then lead-ins."""
    link_terms(draft)
    link_citations(draft)
    refs = link_references(draft, sections)
    link_identifiers(draft)
    consumed = link_precedence(draft, refs)
    emit_references(draft, refs, consumed)
    link_leadins(draft)
