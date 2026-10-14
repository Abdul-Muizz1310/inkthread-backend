"""Reading a multipart upload with the size limit enforced while the body streams (spec 07 § 4)."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.datastructures import UploadFile
from starlette.types import Message

from inkthread.core.errors import FileTooLarge

#: Room for the multipart boundaries and part headers around the file's bytes.
MULTIPART_SLACK = 64 * 1024


def _too_large(limit: int) -> FileTooLarge:
    return FileTooLarge(f"The upload is larger than {limit:,} bytes.", detail={"max_bytes": limit})


async def read_upload(request: Request, limit: int) -> tuple[str | None, bytes]:
    """The `file` field's name and bytes; stops reading as soon as the body passes the limit."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit + MULTIPART_SLACK:
        raise _too_large(limit)
    received = 0

    async def receive() -> Message:
        nonlocal received
        message = await request.receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit + MULTIPART_SLACK:
                raise _too_large(limit)
        return message

    limited = Request(request.scope, receive)
    async with limited.form(max_files=1, max_fields=8) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise RequestValidationError(
                [{"type": "missing", "loc": ("body", "file"), "msg": "Field required"}]
            )
        data = await upload.read(limit + 1)
        if len(data) > limit:
            raise _too_large(limit)
        return upload.filename, data
