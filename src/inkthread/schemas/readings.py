"""The reading DTO (spec 11 § 2, interface I-3)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from inkthread.domain.digest import FindingNote, LinkedTable, VerificationSummary


class ReadingOut(BaseModel):
    """`inkthread.reading/1`: inkgrid's tables, verification summary and findings for a document."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", serialize_by_alias=True, validate_by_name=True
    )

    schema_version: Literal["inkthread.reading/1"] = Field(
        default="inkthread.reading/1", alias="schema"
    )
    document_id: uuid.UUID
    doc_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inkgrid_version: str
    verification: VerificationSummary
    tables: tuple[LinkedTable, ...]
    findings: tuple[FindingNote, ...]
