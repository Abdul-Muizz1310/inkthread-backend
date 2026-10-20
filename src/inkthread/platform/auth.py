"""The platform-token gate (spec 12 § 3), as pure ASGI so event streams pass through untouched."""

from __future__ import annotations

import json
import time
from typing import Final

import structlog
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from inkthread.core.errors import envelope
from inkthread.platform.keys import KeyResolver
from inkthread.platform.token import BASTION_ISS, Principal, TokenRejected, verify

_log = structlog.get_logger(__name__)

PUBLIC_EXACT: Final = frozenset(
    {"/health", "/version", "/metrics", "/docs", "/redoc", "/openapi.json"}
)
PUBLIC_PREFIXES: Final = ("/docs/",)

_MESSAGES: Final = {
    "missing_platform_token": "This route needs an X-Platform-Token.",
    "invalid_platform_token": "The platform token is not valid for inkthread.",
    "platform_auth_unconfigured": "No platform key is configured, so protected routes are closed.",
}


def is_public(path: str) -> bool:
    """Whether a path needs no token. `/docs/...` is public; `/documents` is not."""
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


def token_from(headers: Headers) -> str | None:
    """`X-Platform-Token`, else an `Authorization: Bearer` token; `None` when neither is given."""
    token = headers.get("x-platform-token", "").strip()
    if token:
        return token
    scheme, _, value = headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


class PlatformAuthMiddleware:
    """Refuse a request without a valid token, unless its route is public (spec 12 § 3).

    `enforce_unconfigured=False` (the test settings) lets every request through anonymous while no
    key is configured; otherwise no key means every protected route answers 503.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resolver: KeyResolver,
        demo_mode: bool,
        enforce_unconfigured: bool,
    ) -> None:
        self.app = app
        self._resolver = resolver
        self._demo = demo_mode
        self._enforce = enforce_unconfigured

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or is_public(scope["path"]):
            await self.app(scope, receive, send)
            return
        keys = await self._resolver.keys()
        if not keys.any:
            if self._enforce:
                await _refuse(send, 503, "platform_auth_unconfigured")
                return
            await self.app(scope, receive, send)
            return
        token = token_from(Headers(scope=scope))
        if token is None:
            if not self._demo:
                await _refuse(send, 401, "missing_platform_token")
                return
            _log.warning("platform_token_missing", path=scope["path"], demo_mode=True)
            await self.app(scope, receive, send)
            return
        try:
            principal: Principal = verify(token, keys, now=time.time())
        except TokenRejected as exc:
            _log.warning("platform_token_rejected", check=exc.check, path=scope["path"])
            await _refuse(send, 401, "invalid_platform_token")
            return
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)


async def _refuse(send: Send, status: int, code: str) -> None:
    body = json.dumps(envelope(code, _MESSAGES[code], code)).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="inkthread"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def bastion_only(request: Request) -> bool:
    """slowquery-detective's `authorize` (spec 13 § 1): only a bastion-key caller reads receipts."""
    principal = getattr(request.state, "principal", None)
    return isinstance(principal, Principal) and principal.iss == BASTION_ISS
