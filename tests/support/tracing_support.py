"""Spans a test exported, and readers for the Langfuse attributes on them (spec 14).

`tracing_client` is the production client's configuration (the upload mask included) with an
in-memory exporter in place of the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langfuse import Langfuse
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from inkthread.core import tracing

INPUT = "langfuse.observation.input"
OUTPUT = "langfuse.observation.output"
METADATA = "langfuse.observation.metadata."


def tracing_client(exporter: SpanExporter) -> Langfuse:
    """A client exporting to `exporter` only. A fresh public key: the SDK keeps one per key."""
    return Langfuse(
        public_key=f"pk-lf-test-{uuid4().hex}",
        secret_key="sk-lf-test",
        base_url="http://langfuse.invalid",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
        environment="test",
        mask_otel_spans=tracing.withhold_upload_text,
    )


@dataclass
class Traces:
    """What a test exported."""

    client: Langfuse
    exporter: InMemorySpanExporter

    def spans(self) -> list[ReadableSpan]:
        self.client.flush()
        return sorted(self.exporter.get_finished_spans(), key=lambda s: s.start_time or 0)

    def named(self, name: str) -> list[ReadableSpan]:
        return [s for s in self.spans() if s.name == name]

    def one(self, name: str) -> ReadableSpan:
        found = self.named(name)
        assert len(found) == 1, f"{len(found)} spans named {name!r}"
        return found[0]

    def parent(self, span: ReadableSpan) -> ReadableSpan | None:
        if span.parent is None:
            return None
        return next((s for s in self.spans() if s.context.span_id == span.parent.span_id), None)

    def children(self, span: ReadableSpan) -> list[ReadableSpan]:
        return [
            s
            for s in self.spans()
            if s.parent is not None and s.parent.span_id == span.context.span_id
        ]

    def clear(self) -> None:
        self.client.flush()
        self.exporter.clear()

    @staticmethod
    def attr(span: ReadableSpan, key: str) -> Any:
        return (span.attributes or {}).get(key)

    @staticmethod
    def decoded(span: ReadableSpan, key: str) -> Any:
        raw = (span.attributes or {}).get(key)
        return None if raw is None else json.loads(str(raw))

    @staticmethod
    def type_of(span: ReadableSpan) -> Any:
        return (span.attributes or {}).get("langfuse.observation.type")

    @staticmethod
    def level(span: ReadableSpan) -> str:
        """The level Langfuse derives: the attribute, else ERROR on an error status."""
        explicit = (span.attributes or {}).get("langfuse.observation.level")
        if explicit is not None:
            return str(explicit)
        return "ERROR" if span.status.status_code is StatusCode.ERROR else "DEFAULT"

    @staticmethod
    def status_message(span: ReadableSpan) -> str | None:
        explicit = (span.attributes or {}).get("langfuse.observation.status_message")
        return str(explicit) if explicit is not None else span.status.description

    @staticmethod
    def metadata(span: ReadableSpan) -> dict[str, Any]:
        return {
            key.removeprefix(METADATA): json.loads(str(value))
            for key, value in (span.attributes or {}).items()
            if key.startswith(METADATA)
        }

    @staticmethod
    def everything(span: ReadableSpan) -> str:
        """Every string the span would export: name, attributes, events and status."""
        parts = [span.name, str(span.status.description or "")]
        parts += [f"{k}={v}" for k, v in (span.attributes or {}).items()]
        for event in span.events:
            parts.append(event.name)
            parts += [f"{k}={v}" for k, v in (event.attributes or {}).items()]
        return "\n".join(parts)
