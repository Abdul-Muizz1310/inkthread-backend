"""What inkthread keeps of inkgrid's reading (spec 11 § 1): tables and the verification summary.

`inkthread.reader.digest` builds a `ReadingDigest` from inkgrid's types; the domain never imports
inkgrid. A digest that breaks an invariant is refused at construction, so it is never stored.
"""

from __future__ import annotations

from typing import Annotated, Final, Self

from pydantic import Field, model_validator

from inkthread.domain.model import Bbox, Frozen, Graph, NodeKind

READING_SCHEMA: Final = "inkthread.reading/1"

BlockId = Annotated[str, Field(pattern=r"^b[1-9][0-9]*$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class DefectNote(Frozen):
    """One disagreement the second engine found."""

    code: NonEmpty
    page: int = Field(ge=1)
    message: str


class VerificationSummary(Frozen):
    """inkgrid's verification report, summarised."""

    ok: bool
    engine: NonEmpty
    checked: int = Field(ge=0)
    disagreements: int = Field(ge=0)
    defects: tuple[DefectNote, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.disagreements != len(self.defects):
            msg = (
                f"disagreements is {self.disagreements} but {len(self.defects)} defects are listed"
            )
            raise ValueError(msg)
        if self.ok != (not self.defects):
            msg = f"ok is {self.ok} with {len(self.defects)} defects"
            raise ValueError(msg)
        return self


class TableDigest(Frozen):
    """One inkgrid table: dense rows and GFM Markdown."""

    id: BlockId
    page: int = Field(ge=1)
    bbox: Bbox
    header_rows: int = Field(ge=0)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1)
    markdown: NonEmpty

    @model_validator(mode="after")
    def _rectangular(self) -> Self:
        widths = {len(row) for row in self.rows}
        if len(widths) != 1 or 0 in widths:
            msg = f"table {self.id}: every row needs the same, non-zero width, got {sorted(widths)}"
            raise ValueError(msg)
        if self.header_rows > len(self.rows):
            msg = f"table {self.id}: {self.header_rows} header rows but {len(self.rows)} rows"
            raise ValueError(msg)
        return self


class LinkedTable(TableDigest):
    """A table with the graph node that holds it (`None` when the table was set aside)."""

    node_id: str | None


class FindingNote(Frozen):
    """One inkgrid finding; `page` is `None` when it concerns the whole document."""

    code: NonEmpty
    severity: NonEmpty
    page: int | None = Field(default=None, ge=1)


class ReadingDigest(Frozen):
    """Everything spec 11 keeps from one reading."""

    inkgrid_version: NonEmpty
    verification: VerificationSummary
    tables: tuple[TableDigest, ...] = ()
    findings: tuple[FindingNote, ...] = ()

    @model_validator(mode="after")
    def _unique_tables(self) -> Self:
        seen: set[str] = set()
        for t in self.tables:
            if t.id in seen:
                msg = f"table {t.id} is listed twice"
                raise ValueError(msg)
            seen.add(t.id)
        return self


def link_tables(digest: ReadingDigest, graph: Graph) -> tuple[LinkedTable, ...]:
    """Each table with the id of the `table` node whose source cites its block."""
    owner = {
        block: n.id for n in graph.nodes if n.kind is NodeKind.TABLE for block in n.source.blocks
    }
    return tuple(LinkedTable(**t.model_dump(), node_id=owner.get(t.id)) for t in digest.tables)
