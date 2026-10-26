"""Suite-wide setup.

Tracing is off whatever a local `.env` holds (spec 14 § 1): blank Langfuse keys win over it, so no
test sends spans to Langfuse. Tests that assert on traces take `traces`, a client on an in-memory
exporter with the production upload mask.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tracing_support import Traces, tracing_client

from inkthread.core import tracing


@pytest.fixture
def traces(monkeypatch: pytest.MonkeyPatch) -> Iterator[Traces]:
    exporter = InMemorySpanExporter()
    client = tracing_client(exporter)
    monkeypatch.setattr(tracing, "_client", client)
    yield Traces(client=client, exporter=exporter)
    client.shutdown()
