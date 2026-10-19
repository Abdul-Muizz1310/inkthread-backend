"""Run the reader in a fresh spawned child, one PDF at a time (spec 08 § 3)."""

from __future__ import annotations

import asyncio
import multiprocessing
from dataclasses import dataclass
from typing import Literal

import inkgrid
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from inkthread.domain.digest import ReadingDigest
from inkthread.domain.reading import Reading
from inkthread.reader.adapt import adapt
from inkthread.reader.child import run_child
from inkthread.reader.digest import digest

FailureCode = Literal[
    "pdf_encrypted", "pdf_unreadable", "reader_failed", "read_timeout", "no_text_layer"
]
ChildCode = Literal["pdf_encrypted", "pdf_unreadable", "reader_failed"]
_JOIN_S = 5.0


@dataclass(frozen=True, slots=True)
class ReadSuccess:
    """The reading, one PNG per page rendered at 2x, and what spec 11 keeps of the reading."""

    reading: Reading
    pngs: list[bytes]
    digest: ReadingDigest


@dataclass(frozen=True, slots=True)
class ReadFailure:
    """Why the read failed, as a job error code."""

    code: FailureCode
    message: str


ReadOutcome = ReadSuccess | ReadFailure


class _ChildOk(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_json: str
    report_json: str
    pngs: list[bytes]


class _ChildError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    error: ChildCode
    message: str


_RESULT: TypeAdapter[_ChildOk | _ChildError] = TypeAdapter(_ChildOk | _ChildError)


def _wait(pdf: bytes, timeout_s: float, memory_limit_mb: int) -> ReadFailure | _ChildOk:
    """Blocking: spawn the child, wait for its result or the deadline, and reap it."""
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=run_child, args=(child, pdf, memory_limit_mb, 2.0), name="inkthread-reader"
    )
    proc.start()
    child.close()
    answered = False
    try:
        if not parent.poll(timeout_s):
            return ReadFailure("read_timeout", f"the reader ran past {timeout_s:g} s")
        try:
            raw: object = parent.recv()
            answered = True
        except (EOFError, OSError):
            return ReadFailure("reader_failed", f"the reader exited ({proc.exitcode}) silently")
    finally:
        parent.close()
        # A child that answered exits by itself; one that timed out is terminated at once.
        proc.join(_JOIN_S if answered else 0)
        if proc.is_alive():
            proc.terminate()
            proc.join(_JOIN_S)
        if proc.is_alive():
            proc.kill()
            proc.join()
        proc.close()
    try:
        parsed = _RESULT.validate_python(raw)
    except ValidationError as exc:
        return ReadFailure("reader_failed", f"the reader sent a malformed result: {exc}")
    if isinstance(parsed, _ChildError):
        return ReadFailure(parsed.error, parsed.message)
    return parsed


def _outcome(ok: _ChildOk) -> ReadOutcome:
    try:
        doc = inkgrid.Document.model_validate_json(ok.document_json)
        report = inkgrid.VerificationReport.model_validate_json(ok.report_json)
    except ValidationError as exc:
        return ReadFailure("reader_failed", f"the reading did not validate: {exc}")
    reading = adapt(doc, report)
    if not any(b.kind != "furniture" for b in reading.blocks):
        return ReadFailure("no_text_layer", "the PDF has no text layer; inkthread does not OCR")
    return ReadSuccess(reading=reading, pngs=ok.pngs, digest=digest(doc, report))


async def read_in_child(pdf: bytes, *, timeout_s: float, memory_limit_mb: int = 0) -> ReadOutcome:
    """Read `pdf` in a spawned child without blocking the event loop."""
    waited = await asyncio.to_thread(_wait, pdf, timeout_s, memory_limit_mb)
    if isinstance(waited, ReadFailure):
        return waited
    return await asyncio.to_thread(_outcome, waited)
