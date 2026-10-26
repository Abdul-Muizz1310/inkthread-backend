"""Langfuse tracing: Langfuse v4 through Python SDK v5 (spec 14).

A job is one trace. `job_trace` opens its root, `build-document-graph`, and gives every observation
under it the trace attributes; `step` opens a stage or a lookup, `generation` one HTTP attempt.
An exception never leaves an observation with its message (§ 3): the observation records the
exception's type and the exception is re-raised outside it.

Uploads keep no document text (DR-0029): `withhold_upload_text`, the client's export hook, strips
input, output and unlisted metadata from every span not tagged as a sample's.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from langfuse import (
    Langfuse,
    LangfuseAgent,
    LangfuseChain,
    LangfuseEvaluator,
    LangfuseGeneration,
    LangfuseRetriever,
    propagate_attributes,
)
from langfuse.api import MapValue
from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPatch
from slowquery_detective import current_request_id

from inkthread.core.config import Settings

SERVICE_TAG = "inkthread"
SAMPLE_TAG = "kind:sample"
ROOT = "build-document-graph"
WITHHELD = "withheld"
WITHHELD_NOTE = "uploads keep no document text (DR-0029)"

#: Metadata an upload's spans keep: ids, counts and codes, never document text.
SAFE_METADATA = frozenset(
    {
        "job_id",
        "document_id",
        "stage",
        "status",
        "reason",
        "pages",
        "blocks",
        "nodes",
        "set_aside",
        "edges",
        "accepted",
        "rejected",
        "task",
        "attempt",
        "provider",
        "hit",
        "served_model",
        WITHHELD,
    }
)

_INPUT = "langfuse.observation.input"
_OUTPUT = "langfuse.observation.output"
_METADATA = ("langfuse.observation.metadata.", "langfuse.trace.metadata.")
_TAGS = "langfuse.trace.tags"

DocumentKind = Literal["sample", "upload"]
StepType = Literal["chain", "agent", "evaluator", "retriever"]

Step = LangfuseChain | LangfuseAgent | LangfuseEvaluator | LangfuseRetriever


@dataclass
class _State:
    """The process's client: none until first use or `configure`."""

    client: Langfuse | None = None


_state = _State()


def build_client(cfg: Settings) -> Langfuse:
    """A client for `cfg`: tracing with both keys, a no-op without either."""
    public = cfg.langfuse_public_key.get_secret_value().strip() if cfg.langfuse_public_key else ""
    secret = cfg.langfuse_secret_key.get_secret_value().strip() if cfg.langfuse_secret_key else ""
    if not (public and secret):
        return Langfuse(tracing_enabled=False)
    return Langfuse(
        public_key=public,
        secret_key=secret,
        base_url=cfg.langfuse_base_url,
        environment=cfg.app_env,
        mask_otel_spans=withhold_upload_text,
    )


def configure(cfg: Settings) -> None:
    """Install the client `cfg` asks for; without both keys, leave tracing as it is (off)."""
    public, secret = cfg.langfuse_public_key, cfg.langfuse_secret_key
    if (
        public
        and secret
        and public.get_secret_value().strip()
        and secret.get_secret_value().strip()
    ):
        _state.client = build_client(cfg)


def client() -> Langfuse:
    """The installed client; one no-op client until `configure` installs a real one."""
    if _state.client is None:
        _state.client = Langfuse(tracing_enabled=False)
    return _state.client


def shutdown() -> None:
    """Flush buffered observations and stop the exporter (the app's lifespan end)."""
    if _state.client is not None:
        _state.client.shutdown()


@contextmanager
def _contained[O: Step | LangfuseGeneration](opened: AbstractContextManager[O]) -> Iterator[O]:
    """Open an observation that records a failure's type, never its message (spec 14 § 3)."""
    failure: Exception | None = None
    with opened as observation:
        try:
            yield observation
        except asyncio.CancelledError:
            observation.update(level="ERROR", status_message="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised below, outside the observation
            observation.update(level="ERROR", status_message=type(exc).__name__)
            failure = exc
    if failure is not None:
        raise failure


@contextmanager
def job_trace(
    *, job_id: UUID, document_id: UUID, kind: DocumentKind, file_name: str | None
) -> Iterator[LangfuseChain]:
    """Open `build-document-graph` and give every observation under it the trace attributes.

    The session is the request id the job runs under (spec 13 § 2): bastion sends one for every
    call of a dossier, so its traces group into one session.
    """
    with (
        _contained(
            client().start_as_current_observation(
                as_type="chain", name=ROOT, input={"kind": kind, "file_name": file_name}
            )
        ) as root,
        propagate_attributes(
            trace_name=ROOT,
            session_id=current_request_id(),
            tags=[SERVICE_TAG, f"kind:{kind}"],
            metadata={"job_id": str(job_id), "document_id": str(document_id)},
        ),
    ):
        yield root


@contextmanager
def step(
    name: str, *, as_type: StepType, metadata: Mapping[str, object] | None = None
) -> Iterator[Step]:
    """A stage of the pipeline or a recorded-answer lookup."""
    with _contained(_open_step(name, as_type, dict(metadata) if metadata else None)) as observed:
        yield observed


def _open_step(
    name: str, as_type: StepType, metadata: dict[str, object] | None
) -> AbstractContextManager[Step]:
    lf = client()
    match as_type:
        case "chain":
            return lf.start_as_current_observation(as_type="chain", name=name, metadata=metadata)
        case "agent":
            return lf.start_as_current_observation(as_type="agent", name=name, metadata=metadata)
        case "evaluator":
            return lf.start_as_current_observation(
                as_type="evaluator", name=name, metadata=metadata
            )
        case "retriever":
            return lf.start_as_current_observation(
                as_type="retriever", name=name, metadata=metadata
            )


@contextmanager
def generation(
    name: str,
    *,
    model: str,
    messages: object,
    parameters: Mapping[str, MapValue],
    metadata: Mapping[str, object],
) -> Iterator[LangfuseGeneration]:
    """One HTTP attempt at a model."""
    opened = client().start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=messages,
        model_parameters=dict(parameters),
        metadata=dict(metadata),
    )
    with _contained(opened) as observation:
        yield observation


def usage_details(
    *,
    prompt: int | None = None,
    completion: int | None = None,
    cached: int | None = None,
    reasoning: int | None = None,
) -> dict[str, int]:
    """OpenRouter's token counts as Langfuse's exclusive usage buckets.

    OpenRouter counts cached tokens inside `prompt` and reasoning tokens inside `completion`;
    Langfuse adds buckets up, so each detail is taken out of its total and never exceeds it. A total
    that was not reported drops its buckets, details included.
    """
    buckets: dict[str, int] = {}
    if prompt is not None:
        hit = min(cached or 0, prompt)
        buckets["input"] = prompt - hit
        if hit:
            buckets["input_cached_tokens"] = hit
    if completion is not None:
        thought = min(reasoning or 0, completion)
        buckets["output"] = completion - thought
        if thought:
            buckets["output_reasoning_tokens"] = thought
    return buckets


def cost_details(cost: float | None) -> dict[str, float] | None:
    """The cost OpenRouter reported for an attempt, as its total (USD)."""
    return None if cost is None else {"total": cost}


def withhold_upload_text(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult | None:
    """Spec 14 § 3, fail-closed: unless a span is tagged as a sample's, export no text from it.

    The span loses its input, its output and every metadata key outside `SAFE_METADATA`, and is
    marked `withheld`. Names, types, models, usage, cost, levels and status messages stay.
    """
    patches = {}
    for key, span in params.spans.items():
        tags = span.attributes.get(_TAGS)
        if isinstance(tags, tuple | list) and SAMPLE_TAG in tags:
            continue
        doomed = tuple(name for name in span.attributes if _holds_text(name))
        patches[key] = OtelSpanPatch(
            delete_attributes=doomed,
            set_attributes={_METADATA[0] + WITHHELD: json.dumps(WITHHELD_NOTE)},
        )
    return MaskOtelSpansResult(span_patches=patches) if patches else None


def _holds_text(attribute: str) -> bool:
    if attribute in (_INPUT, _OUTPUT):
        return True
    for prefix in _METADATA:
        if attribute.startswith(prefix):
            return attribute.removeprefix(prefix) not in SAFE_METADATA
    return False
