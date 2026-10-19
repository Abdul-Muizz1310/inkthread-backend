"""The trusted public keys (spec 12 § 2): parsed from configuration, or bastion's fetched by URL."""

from __future__ import annotations

import asyncio
import base64
import binascii
import time
from collections.abc import Awaitable, Callable

import httpx
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, ValidationError

from inkthread.platform.token import TrustedKeys

_log = structlog.get_logger(__name__)

KEY_TTL_S = 3600.0
RETRY_S = 60.0
FETCH_TIMEOUT_S = 5.0

Fetch = Callable[[str], Awaitable[str]]


def parse_public_key(value: str) -> Ed25519PublicKey:
    """A base64 SPKI DER Ed25519 public key; a BOM and edge whitespace are ignored."""
    cleaned = value.strip().lstrip("﻿").strip()
    try:
        der = base64.b64decode(cleaned, validate=True)
        key = serialization.load_der_public_key(der)
    except (binascii.Error, ValueError) as exc:
        msg = "not a base64 Ed25519 public key (SPKI DER)"
        raise ValueError(msg) from exc
    if not isinstance(key, Ed25519PublicKey):
        msg = "not a base64 Ed25519 public key (SPKI DER)"
        raise ValueError(msg)  # noqa: TRY004 - a configuration value error, not a type error
    return key


class _PublicKeyOut(BaseModel):
    """bastion's public-key document."""

    model_config = ConfigDict(extra="ignore")
    publicKey: str  # noqa: N815 - bastion's field name


async def fetch_public_key(url: str) -> str:
    """`publicKey` from bastion's public-key URL."""
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S) as client:
        response = await client.get(url)
        response.raise_for_status()
    try:
        return _PublicKeyOut.model_validate_json(response.content).publicKey
    except ValidationError as exc:
        msg = "the public-key document has no publicKey"
        raise ValueError(msg) from exc


class KeyResolver:
    """Configured keys, and bastion's key from its URL kept for an hour (spec 12 T-PT-17)."""

    def __init__(
        self,
        *,
        bastion: str | None,
        bastion_url: str | None,
        frontend: str | None,
        fetch: Fetch = fetch_public_key,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = KEY_TTL_S,
        retry_s: float = RETRY_S,
    ) -> None:
        self._bastion = parse_public_key(bastion) if bastion else None
        self._frontend = parse_public_key(frontend) if frontend else None
        self._url = None if bastion else bastion_url
        self._fetch = fetch
        self._clock = clock
        self._ttl = ttl_s
        self._retry = retry_s
        self._fetched: Ed25519PublicKey | None = None
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def keys(self) -> TrustedKeys:
        """The keys trusted right now."""
        bastion = self._bastion if self._bastion is not None else await self._from_url()
        return TrustedKeys(bastion=bastion, frontend=self._frontend)

    async def _from_url(self) -> Ed25519PublicKey | None:
        if self._url is None or self._clock() < self._next:
            return self._fetched
        async with self._lock:
            now = self._clock()
            if now < self._next:
                return self._fetched
            try:
                self._fetched = parse_public_key(await self._fetch(self._url))
                self._next = now + self._ttl
            except Exception as exc:  # noqa: BLE001 - any failure keeps the last good key
                _log.warning("bastion_key_fetch_failed", error=type(exc).__name__)
                self._next = now + self._retry
        return self._fetched
