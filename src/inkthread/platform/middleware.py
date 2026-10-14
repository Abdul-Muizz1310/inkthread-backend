"""Request ids (spec 07 § 4): echo a sane `X-Request-Id`, else make one; bind it to the logs."""

from __future__ import annotations

import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from inkthread.core.logging import bind_request_id

_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def accept_request_id(incoming: str | None) -> str:
    """The incoming id when it is short and plain, else a fresh one."""
    if incoming is not None and _SAFE.match(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestIdMiddleware:
    """Pure ASGI, so streaming responses pass through untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = accept_request_id(Headers(scope=scope).get("x-request-id"))
        scope.setdefault("state", {})["request_id"] = rid
        bind_request_id(rid)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-Id"] = rid
            await send(message)

        await self.app(scope, receive, send_with_id)
