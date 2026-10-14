"""OpenRouter's model catalogue: which response formats a model claims to support (spec 05 § 6).

`GET {base}/models` needs no key and costs no request. It is cached for 24 hours. The catalogue is
not trusted (a 400 still moves the cascade on); it only picks the request shape.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import structlog
from pydantic import BaseModel, ValidationError

_log = structlog.get_logger(__name__)
CATALOG_TTL_S = 24 * 3600.0


@dataclass(frozen=True)
class Capabilities:
    """What a model lists in `supported_parameters`."""

    structured_outputs: bool
    response_format: bool


_NONE = Capabilities(structured_outputs=False, response_format=False)


class _Entry(BaseModel):
    id: str
    supported_parameters: list[str] | None = None


class _Listing(BaseModel):
    data: list[_Entry]


class ModelCatalog:
    """Capabilities by slug, fetched once a day through the injected client."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        *,
        ttl_s: float = CATALOG_TTL_S,
        timeout_s: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._url = base_url.rstrip("/") + "/models"
        self._ttl = ttl_s
        self._timeout = timeout_s
        self._clock = clock
        self._caps: dict[str, Capabilities] | None = None
        self._fetched_at = 0.0

    async def capabilities(self, slug: str) -> Capabilities:
        """The model's capabilities; an unknown slug or a failed fetch gives none."""
        if self._caps is None or self._clock() - self._fetched_at >= self._ttl:
            await self._refresh()
        return (self._caps or {}).get(slug, _NONE)

    async def _refresh(self) -> None:
        try:
            response = await self._http.get(self._url, timeout=self._timeout)
            response.raise_for_status()
            listing = _Listing.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            _log.warning("model_catalog_unavailable", error=type(exc).__name__)
            return
        caps: dict[str, Capabilities] = {}
        for entry in listing.data:
            params = set(entry.supported_parameters or ())
            caps[entry.id] = Capabilities(
                structured_outputs="structured_outputs" in params,
                response_format="response_format" in params,
            )
        self._caps = caps
        self._fetched_at = self._clock()
