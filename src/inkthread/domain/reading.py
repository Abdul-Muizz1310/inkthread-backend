"""What the domain needs from inkgrid's reading (spec 02 § 1).

`inkthread.reader.adapt` builds a `Reading` from an `inkgrid.Document` and its `VerificationReport`.
The domain never imports inkgrid, so its tests build Readings from literals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from inkthread.domain.model import Bbox, PageSize

BlockKind = Literal[
    "heading", "paragraph", "list_item", "footnote", "definition", "table", "furniture"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RRegion(_Frozen):
    """One page's box of a block."""

    page: int = Field(ge=1)
    bbox: Bbox


class RWord(_Frozen):
    """A word, aligned to its block's text (`start`/`end` null when it could not be aligned)."""

    start: int | None
    end: int | None
    page: int = Field(ge=1)
    bbox: Bbox
    hidden: bool = False
    superscript: bool = False
    text: str


class RCell(_Frozen):
    """A table cell as inkgrid reads it; `bbox` is in page coordinates."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(ge=1)
    col_span: int = Field(ge=1)
    text: str
    carried: bool = False
    markers: tuple[str, ...] = ()
    page: int = Field(ge=1)
    bbox: Bbox | None = None


class RGrid(_Frozen):
    """A table's grid."""

    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    header_rows: int = Field(ge=0)
    banner_rows: tuple[int, ...] = ()
    source: Literal["lattice", "corridor"]
    cells: tuple[RCell, ...]


class RBlock(_Frozen):
    """One inkgrid block, in reading order."""

    id: str
    key: str
    kind: BlockKind
    text: str
    regions: tuple[RRegion, ...]
    words: tuple[RWord, ...] = ()
    markers: tuple[str, ...] = ()
    level: int | None = None
    number: str | None = None
    label: str | None = None
    term: str | None = None
    body: str | None = None
    role: str | None = None
    grid: RGrid | None = None

    @property
    def page(self) -> int:
        """The first page the block touches."""
        return self.regions[0].page if self.regions else 1


class RLink(_Frozen):
    """A footnote call or a table continuation."""

    kind: Literal["footnote_call", "continuation"]
    from_block: str
    from_cell: tuple[int, int] | None = None
    to_block: str | None
    label: str | None = None
    method: Literal["superscript", "parenthetical", "named"] | None = None
    status: Literal["resolved", "unresolved", "rejected"]
    reason: str | None = None


class RFinding(_Frozen):
    """A document-level inkgrid finding."""

    code: str
    severity: str
    page: int | None = None
    detail: str | None = None


class RDefect(_Frozen):
    """A defect inkgrid's verifier found against the page."""

    code: str
    block: str | None
    cell: tuple[int, int] | None = None
    page: int | None = None
    detail: str | None = None


class Reading(_Frozen):
    """Everything the pipeline reads from inkgrid for one PDF."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_name: str | None = None
    pages: tuple[PageSize, ...]
    blocks: tuple[RBlock, ...]
    links: tuple[RLink, ...] = ()
    findings: tuple[RFinding, ...] = ()
    defects: tuple[RDefect, ...] = ()
    producer: dict[str, str | None] = Field(default_factory=dict)
    verified: bool = False

    def block(self, block_id: str) -> RBlock:
        """The block with this id."""
        for b in self.blocks:
            if b.id == block_id:
                return b
        msg = f"no block {block_id}"
        raise KeyError(msg)
