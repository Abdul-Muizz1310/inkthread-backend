"""The `inkthread.graph/1` contract (spec 01).

Every model is frozen and forbids extra fields. Construction runs the invariants of spec 01 § 7, so
an invalid graph cannot exist in memory.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkthread.domain.ids import edge_id

GRAPH_SCHEMA = "inkthread.graph/1"


class Frozen(BaseModel):
    """Base for every contract type."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", serialize_by_alias=True, validate_by_name=True
    )


class NodeKind(StrEnum):
    """What shape a node has."""

    DOCUMENT = "document"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    NOTE = "note"
    DEFINITION = "definition"
    TERM = "term"
    EXTERNAL = "external"


PART_KINDS = frozenset(
    {NodeKind.PARAGRAPH, NodeKind.LIST_ITEM, NodeKind.TABLE, NodeKind.NOTE, NodeKind.DEFINITION}
)
UNPLACED_KINDS = frozenset({NodeKind.DOCUMENT, NodeKind.TERM, NodeKind.EXTERNAL})


class EdgeFamily(StrEnum):
    """Legend groups; edges are coloured by family."""

    STRUCTURE = "structure"
    NOTES = "notes"
    TERMS = "terms"
    REFERENCES = "references"
    LOGIC = "logic"


class EdgeType(StrEnum):
    """How one part depends on another. Declaration order is the graph's edge order."""

    CONTAINS = "contains"
    CONTINUES = "continues"
    CITES_NOTE = "cites_note"
    DEFINES = "defines"
    USES_TERM = "uses_term"
    REFERS_TO = "refers_to"
    CITES_EXTERNAL = "cites_external"
    GOVERNS = "governs"
    QUALIFIES = "qualifies"
    OVERRIDES = "overrides"
    ILLUSTRATES = "illustrates"


EDGE_FAMILY: Mapping[EdgeType, EdgeFamily] = {
    EdgeType.CONTAINS: EdgeFamily.STRUCTURE,
    EdgeType.CONTINUES: EdgeFamily.STRUCTURE,
    EdgeType.CITES_NOTE: EdgeFamily.NOTES,
    EdgeType.DEFINES: EdgeFamily.TERMS,
    EdgeType.USES_TERM: EdgeFamily.TERMS,
    EdgeType.REFERS_TO: EdgeFamily.REFERENCES,
    EdgeType.CITES_EXTERNAL: EdgeFamily.REFERENCES,
    EdgeType.GOVERNS: EdgeFamily.LOGIC,
    EdgeType.QUALIFIES: EdgeFamily.LOGIC,
    EdgeType.OVERRIDES: EdgeFamily.LOGIC,
    EdgeType.ILLUSTRATES: EdgeFamily.LOGIC,
}
EDGE_ORDER: Mapping[EdgeType, int] = {t: i for i, t in enumerate(EdgeType)}
LOGIC_TYPES = frozenset(t for t, f in EDGE_FAMILY.items() if f is EdgeFamily.LOGIC)


class Role(StrEnum):
    """What a part does. Declaration order is the order roles are listed in."""

    OBLIGATION = "obligation"
    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    CONDITION = "condition"
    EXCEPTION = "exception"
    DEFINITION = "definition"
    COMPUTATION = "computation"
    METHOD = "method"
    PROCEDURE = "procedure"
    TEMPORAL = "temporal"
    QUANTITATIVE = "quantitative"
    SCOPE = "scope"
    CONVENTION = "convention"
    EXAMPLE = "example"
    EXTERNAL_POINTER = "external_pointer"
    ADMINISTRATIVE = "administrative"
    SUMMARY = "summary"
    CLAIM = "claim"


ROLE_ORDER: Mapping[Role, int] = {r: i for i, r in enumerate(Role)}


class Basis(StrEnum):
    """Who stands behind an element: the text in so many words, or a model's reading of it."""

    EXPLICIT = "explicit"
    SEMANTIC = "semantic"


class EvidenceSide(StrEnum):
    """Which node's text an edge's evidence sits in."""

    SOURCE = "source"
    TARGET = "target"


class FlagCode(StrEnum):
    """Marks of what is missing or doubtful. Nothing is withheld; it is flagged."""

    HIDDEN_TEXT = "hidden_text"
    TEXT_DEFECT = "text_defect"
    HEADER_NOT_FOUND = "header_not_found"
    NOTE_NOT_FOUND = "note_not_found"
    REFERENCE_UNRESOLVED = "reference_unresolved"
    MULTIPLE_DEFINITIONS = "multiple_definitions"
    MERGED_HEADING = "merged_heading"
    CONTESTED = "contested"
    MODEL_UNAVAILABLE = "model_unavailable"
    TRUNCATED_FOR_MODEL = "truncated_for_model"


class ReasonCode(StrEnum):
    """Why an element has the confidence it has (spec 06 § 1)."""

    VERIFIED_TEXT = "verified_text"
    TEXT_DEFECT = "text_defect"
    EXPLICIT_RULE = "explicit_rule"
    EXPLICIT_INKGRID = "explicit_inkgrid"
    WEAK_RULE = "weak_rule"
    SEMANTIC_AGENT = "semantic_agent"
    VERIFIER_SUPPORTED = "verifier_supported"
    VERIFIER_REJECTED = "verifier_rejected"
    VERIFIER_ABSTAINED = "verifier_abstained"
    VERIFIER_UNAVAILABLE = "verifier_unavailable"
    UNRESOLVED_PARTS = "unresolved_parts"
    HIDDEN_TEXT = "hidden_text"
    TARGET_DEFECT = "target_defect"


class Severity(StrEnum):
    """How much a reason weighs: info and advice → A, flag → B, doubt → C, critical → D."""

    INFO = "info"
    ADVICE = "advice"
    FLAG = "flag"
    DOUBT = "doubt"
    CRITICAL = "critical"


class Tier(StrEnum):
    """The confidence tier: the worst severity among an element's reasons."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Actor(StrEnum):
    """What made an element."""

    INKGRID = "inkgrid"
    RULE = "rule"
    AGENT = "agent"
    VERIFIER = "verifier"


MODEL_ACTORS = frozenset({Actor.AGENT, Actor.VERIFIER})


class Span(Frozen):
    """A verbatim run of a node's text: `quote == text[start:end]`."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.end <= self.start or len(self.quote) != self.end - self.start:
            msg = f"span [{self.start}, {self.end}) does not fit its quote of {len(self.quote)}"
            raise ValueError(msg)
        return self

    @classmethod
    def of(cls, text: str, start: int, end: int) -> Span:
        """The span of `text[start:end]`; raises ValueError when the bounds fall outside it."""
        if not 0 <= start < end <= len(text):
            msg = f"span [{start}, {end}) is outside a text of length {len(text)}"
            raise ValueError(msg)
        return cls(start=start, end=end, quote=text[start:end])

    def fits(self, text: str) -> bool:
        """Whether this span is a valid slice of `text`."""
        return self.end <= len(text) and text[self.start : self.end] == self.quote


Bbox = tuple[float, float, float, float]


class Region(Frozen):
    """Where on a page a node sits: PDF points, unrotated page, origin top-left."""

    page: int = Field(ge=1)
    bbox: Bbox


class Maker(Frozen):
    """What made an element: inkgrid, a rule (by id) or a model (task id, slug, request key)."""

    actor: Actor
    id: str = Field(min_length=1)
    model: str | None = None
    request_key: str | None = None

    @model_validator(mode="after")
    def _model_fields(self) -> Self:
        needs = self.actor in MODEL_ACTORS
        has = self.model is not None and self.request_key is not None
        if needs != has or (not needs and (self.model or self.request_key)):
            msg = "model and request_key are set exactly when the actor is a model"
            raise ValueError(msg)
        return self


class Reason(Frozen):
    """One piece of evidence about an element's confidence."""

    code: ReasonCode
    severity: Severity
    detail: str | None = None


class Confidence(Frozen):
    """Tier (decisive), score (for sorting) and the reasons behind both."""

    tier: Tier
    score: float = Field(ge=0.0, le=1.0)
    reasons: tuple[Reason, ...] = ()


class Verdict(Frozen):
    """A verifier model's judgement of an agent claim."""

    verdict: Literal["supported", "unsupported", "abstain"]
    model: str
    request_key: str


class Flag(Frozen):
    """A mark on an element."""

    code: FlagCode
    detail: str | None = None


class Anchor(Frozen):
    """The table cell an edge's evidence sits in."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)


def _check_basis(basis: Basis, maker: Maker) -> None:
    if (basis is Basis.SEMANTIC) != (maker.actor is Actor.AGENT):
        msg = "basis is semantic exactly when an agent made the element"
        raise ValueError(msg)


class RoleAssignment(Frozen):
    """One role on one node, with the cue that justifies it."""

    role: Role
    evidence: Span | None = None
    made_by: Maker
    basis: Basis
    confidence: Confidence
    verdict: Verdict | None = None

    @model_validator(mode="after")
    def _basis(self) -> Self:
        _check_basis(self.basis, self.made_by)
        return self


class CellInfo(Frozen):
    """One table cell with its verbatim header path and row labels (spec 02 § 6)."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(ge=1)
    col_span: int = Field(ge=1)
    text: str
    is_header: bool
    header_path: tuple[str, ...] = ()
    row_labels: tuple[str, ...] = ()
    markers: tuple[str, ...] = ()
    carried: bool = False
    page: int = Field(ge=1)
    bbox: Bbox | None = None


class TableInfo(Frozen):
    """A table's grid. Cells tile it exactly once."""

    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    header_rows: int = Field(ge=0)
    banner_rows: tuple[int, ...] = ()
    source: Literal["lattice", "corridor"]
    cells: tuple[CellInfo, ...]

    @model_validator(mode="after")
    def _tiles(self) -> Self:
        covered: Counter[tuple[int, int]] = Counter()
        for c in self.cells:
            if c.row + c.row_span > self.n_rows or c.col + c.col_span > self.n_cols:
                msg = f"cell r{c.row}c{c.col} spills out of the grid, so the cells do not tile it"
                raise ValueError(msg)
            for r in range(c.row, c.row + c.row_span):
                for k in range(c.col, c.col + c.col_span):
                    covered[r, k] += 1
        expected = {(r, k) for r in range(self.n_rows) for k in range(self.n_cols)}
        if set(covered) != expected or any(n != 1 for n in covered.values()):
            msg = "cells must tile the grid exactly once"
            raise ValueError(msg)
        return self


class Unresolved(Frozen):
    """A call or reference that found no target."""

    kind: Literal["note", "reference"]
    text: str
    span: Span | None = None
    candidates: tuple[str, ...] = ()
    reason: str


class NodeSource(Frozen):
    """The inkgrid blocks a node came from."""

    blocks: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()


class Node(Frozen):
    """One part, section, term or outside source of the document."""

    id: str = Field(min_length=3)
    kind: NodeKind
    label: str
    label_truncated: bool
    text: str
    order: int = Field(ge=0)
    section: str | None
    depth: int = Field(ge=0)
    regions: tuple[Region, ...] = ()
    roles: tuple[RoleAssignment, ...] = ()
    table: TableInfo | None = None
    marker: str | None = None
    flags: tuple[Flag, ...] = ()
    hidden_spans: tuple[Span, ...] = ()
    unresolved: tuple[Unresolved, ...] = ()
    confidence: Confidence
    source: NodeSource
    made_by: Maker

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if (self.table is not None) != (self.kind is NodeKind.TABLE):
            msg = f"table info is present exactly on table nodes ({self.id})"
            raise ValueError(msg)
        if not self.regions and self.kind not in UNPLACED_KINDS:
            msg = f"a {self.kind} needs at least one page region ({self.id})"
            raise ValueError(msg)
        if not self.text and self.kind is not NodeKind.DOCUMENT:
            msg = f"only the document node may have empty text ({self.id})"
            raise ValueError(msg)
        roles = [a.role for a in self.roles]
        if len(set(roles)) != len(roles):
            msg = f"a role appears twice on {self.id}"
            raise ValueError(msg)
        spans = [a.evidence for a in self.roles if a.evidence is not None]
        spans += list(self.hidden_spans)
        spans += [u.span for u in self.unresolved if u.span is not None]
        for span in spans:
            if not span.fits(self.text):
                msg = f"evidence span {span.start}-{span.end} does not fit the text of {self.id}"
                raise ValueError(msg)
        return self


class Edge(Frozen):
    """A typed, directed relationship between two nodes."""

    id: str = Field(min_length=3)
    type: EdgeType
    family: EdgeFamily
    source: str
    target: str
    basis: Basis
    evidence: Span | None = None
    evidence_on: EvidenceSide = EvidenceSide.SOURCE
    anchor: Anchor | None = None
    label: str | None = None
    method: str = Field(min_length=1)
    made_by: Maker
    confidence: Confidence
    flags: tuple[Flag, ...] = ()
    verdict: Verdict | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.source == self.target:
            msg = f"an edge may not loop ({self.source})"
            raise ValueError(msg)
        if EDGE_FAMILY[self.type] is not self.family:
            msg = f"{self.type} belongs to {EDGE_FAMILY[self.type]}, not {self.family}"
            raise ValueError(msg)
        _check_basis(self.basis, self.made_by)
        return self

    @classmethod
    def make(
        cls,
        *,
        type: EdgeType,  # noqa: A002 - the contract's field name
        source: str,
        target: str,
        basis: Basis,
        method: str,
        made_by: Maker,
        confidence: Confidence,
        evidence: Span | None = None,
        evidence_on: EvidenceSide = EvidenceSide.SOURCE,
        anchor: Anchor | None = None,
        label: str | None = None,
        flags: tuple[Flag, ...] = (),
        verdict: Verdict | None = None,
    ) -> Edge:
        """Build an edge, deriving its id and family."""
        return cls(
            id=edge_id(type.value, source, target, method, label),
            type=type,
            family=EDGE_FAMILY[type],
            source=source,
            target=target,
            basis=basis,
            evidence=evidence,
            evidence_on=evidence_on,
            anchor=anchor,
            label=label,
            method=method,
            made_by=made_by,
            confidence=confidence,
            flags=flags,
            verdict=verdict,
        )


class SetAside(Frozen):
    """An inkgrid block that is not content, kept verbatim."""

    block: str
    kind: Literal["furniture", "toc"]
    text: str
    page: int = Field(ge=1)
    bbox: Bbox
    reason: str


class Finding(Frozen):
    """A document-level finding: inkgrid's, or the pipeline's."""

    code: str
    severity: str
    page: int | None = None
    detail: str | None = None


class PageSize(Frozen):
    """A page's size in PDF points."""

    number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class DocumentInfo(Frozen):
    """What was read."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_name: str | None
    title: str | None
    title_node: str | None
    page_count: int = Field(ge=1)
    pages: tuple[PageSize, ...]


class GraphStats(Frozen):
    """Counts derived from the content only."""

    nodes_by_kind: dict[str, int]
    edges_by_type: dict[str, int]
    roles: dict[str, int]
    tiers: dict[str, int]


class RejectedClaim(Frozen):
    """A model claim that failed grounding (spec 05 § 4)."""

    task: str
    request_key: str
    item: str
    reason: str


class Provenance(Frozen):
    """Versions, models, the op log's head and the graph's own hash."""

    pipeline_version: str
    inkgrid_version: str
    prompts_hash: str
    models: dict[str, str]
    ops_head: str
    ops_count: int = Field(ge=0)
    graph_hash: str
    rejected: tuple[RejectedClaim, ...] = ()


_TARGET_KIND: Mapping[EdgeType, frozenset[NodeKind]] = {
    EdgeType.CITES_NOTE: frozenset({NodeKind.NOTE}),
    EdgeType.DEFINES: frozenset({NodeKind.TERM}),
    EdgeType.USES_TERM: frozenset({NodeKind.TERM}),
    EdgeType.CITES_EXTERNAL: frozenset({NodeKind.EXTERNAL}),
}


class Graph(Frozen):
    """The product: a document as a knowledge graph of its own parts."""

    schema_version: Literal["inkthread.graph/1"] = Field(
        default="inkthread.graph/1", alias="schema"
    )
    document: DocumentInfo
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    set_aside: tuple[SetAside, ...] = ()
    findings: tuple[Finding, ...] = ()
    stats: GraphStats
    provenance: Provenance

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        nodes = {}
        for n in self.nodes:
            if n.id in nodes:
                msg = f"duplicate node id {n.id}"
                raise ValueError(msg)
            nodes[n.id] = n
        edge_ids = [e.id for e in self.edges]
        if len(set(edge_ids)) != len(edge_ids):
            msg = "duplicate edge id"
            raise ValueError(msg)
        documents = [n for n in self.nodes if n.kind is NodeKind.DOCUMENT]
        if len(documents) != 1:
            msg = f"a graph has exactly one document node, not {len(documents)}"
            raise ValueError(msg)
        doc = documents[0]
        if doc.order != 0 or doc.section is not None or doc.depth != 0:
            msg = "the document node has order 0, no section and depth 0"
            raise ValueError(msg)
        self._check_edges(nodes)
        self._check_tree(nodes, doc.id)
        orders = [n.order for n in self.nodes if n.kind is not NodeKind.DOCUMENT]
        if orders != sorted(set(orders)):
            msg = "node order must be unique and increasing"
            raise ValueError(msg)
        return self

    def _check_edges(self, nodes: Mapping[str, Node]) -> None:
        for e in self.edges:
            for end in (e.source, e.target):
                if end not in nodes:
                    msg = f"edge {e.id} names unknown node {end}"
                    raise ValueError(msg)
            allowed = _TARGET_KIND.get(e.type)
            if allowed is not None and nodes[e.target].kind not in allowed:
                msg = f"{e.type} must point at {sorted(allowed)}, not {nodes[e.target].kind}"
                raise ValueError(msg)
            if e.type is EdgeType.CONTAINS and nodes[e.source].kind not in {
                NodeKind.SECTION,
                NodeKind.DOCUMENT,
            }:
                msg = "contains must come from a section or the document"
                raise ValueError(msg)
            if e.evidence is not None:
                holder = nodes[e.source if e.evidence_on is EvidenceSide.SOURCE else e.target]
                if not e.evidence.fits(holder.text):
                    msg = f"edge {e.id}: evidence does not fit the text of {holder.id}"
                    raise ValueError(msg)
            if e.anchor is not None:
                table = nodes[e.source].table
                if table is None or e.anchor.row >= table.n_rows or e.anchor.col >= table.n_cols:
                    msg = f"edge {e.id}: anchor is outside its source table"
                    raise ValueError(msg)

    def _check_tree(self, nodes: Mapping[str, Node], doc_id: str) -> None:
        parents: dict[str, list[str]] = {}
        for e in self.edges:
            if e.type is EdgeType.CONTAINS:
                parents.setdefault(e.target, []).append(e.source)
        for n in self.nodes:
            if n.kind in UNPLACED_KINDS:
                if n.id in parents:
                    msg = f"{n.kind} {n.id} may not be contained"
                    raise ValueError(msg)
                continue
            got = parents.get(n.id, [])
            if len(got) != 1 or got[0] != n.section:
                msg = f"{n.id} needs exactly one incoming contains edge, from {n.section}"
                raise ValueError(msg)
            if n.section not in nodes or nodes[n.section].kind not in {
                NodeKind.SECTION,
                NodeKind.DOCUMENT,
            }:
                msg = f"{n.id}'s section must be a section or the document"
                raise ValueError(msg)
        # every placed node must reach the document (no cycles in the tree)
        for n in self.nodes:
            seen: set[str] = set()
            cursor: str | None = n.id
            while cursor is not None and cursor != doc_id:
                if cursor in seen:
                    msg = f"the contains tree has a cycle at {cursor}"
                    raise ValueError(msg)
                seen.add(cursor)
                cursor = nodes[cursor].section
