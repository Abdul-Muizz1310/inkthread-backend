"""The op log: every change to the draft, hash-chained (spec 06 § 3).

Ops carry structure, never text: a span is offsets, a quote is its sha256.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from inkthread.canon import cjson, sha256_hex

OpKind = Literal[
    "set_aside",
    "add_node",
    "add_edge",
    "add_role",
    "add_flag",
    "add_unresolved",
    "verdict",
    "reject",
]


class Op(BaseModel):
    """One recorded decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(ge=1)
    stage: str
    kind: OpKind
    target: str
    actor: str
    method: str
    model: str | None = None
    request_key: str | None = None
    detail: str | None = None


def genesis(pdf_sha256: str, pipeline_version: str) -> str:
    """The chain's first parent: it names the input and the pipeline version."""
    return sha256_hex(f"inkthread-oplog\x1f{pdf_sha256}\x1f{pipeline_version}")


def chain(ops: Sequence[Op], parent: str) -> str:
    """Fold ops into the head hash."""
    head = parent
    for o in ops:
        head = sha256_hex(cjson(o.model_dump()) + "\x1f" + head)
    return head


def verify(
    ops: Sequence[Op], head: str, count: int, pdf_sha256: str, pipeline_version: str
) -> bool:
    """Recompute the chain; a changed, dropped or cut-off op fails (FeeLedger X-17)."""
    if len(ops) != count:
        return False
    if [o.seq for o in ops] != list(range(1, count + 1)):
        return False
    return chain(ops, genesis(pdf_sha256, pipeline_version)) == head
