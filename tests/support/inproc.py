"""An in-process reader for pipeline tests (production reads in a child process)."""

from __future__ import annotations

import inkgrid

from inkthread.reader.adapt import adapt
from inkthread.reader.process import ReadFailure, ReadOutcome, ReadSuccess


async def read_inprocess(pdf: bytes) -> ReadOutcome:
    try:
        doc = inkgrid.read(pdf)
    except inkgrid.InkgridError as err:
        return ReadFailure(code="pdf_unreadable", message=str(err))
    reading = adapt(doc, inkgrid.verify(doc, pdf))
    if not any(b.kind != "furniture" for b in reading.blocks):
        return ReadFailure(code="no_text_layer", message="no text layer")
    return ReadSuccess(reading=reading, pngs=[b"png"] * len(reading.pages))
