"""The blob store: PDFs, page images and page geometry (spec 08 § 2)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

_KEY = re.compile(r"^[a-z0-9][a-z0-9/_.-]*$")


def check_key(key: str) -> str:
    """Keys are relative, lower-case and never climb out of the store."""
    if not _KEY.match(key) or ".." in key.split("/"):
        msg = f"bad blob key {key!r}"
        raise ValueError(msg)
    return key


class BlobStore(Protocol):
    """Where bytes live."""

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete_prefix(self, prefix: str) -> None: ...


class LocalBlobStore:
    """A directory on disk, for development and tests."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def put(self, key: str, data: bytes, content_type: str) -> None:  # noqa: ARG002
        path = self._root / check_key(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes | None:
        path = self._root / check_key(key)
        if not await asyncio.to_thread(path.is_file):
            return None
        return await asyncio.to_thread(path.read_bytes)

    async def delete_prefix(self, prefix: str) -> None:
        base = self._root / check_key(prefix.rstrip("/"))

        def _remove() -> None:
            if base.is_file():
                base.unlink()
            elif base.is_dir():
                for p in sorted(base.rglob("*"), reverse=True):
                    p.unlink() if p.is_file() else p.rmdir()
                base.rmdir()

        await asyncio.to_thread(_remove)


class R2BlobStore:
    """Cloudflare R2 through its S3 API; boto3 calls run in worker threads."""

    def __init__(self, client: S3Client, bucket: str, prefix: str) -> None:
        self._s3 = client
        self._bucket = bucket
        self._prefix = prefix

    def _k(self, key: str) -> str:
        return self._prefix + check_key(key)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket,
            Key=self._k(key),
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes | None:
        def _get() -> bytes | None:
            try:
                obj = self._s3.get_object(Bucket=self._bucket, Key=self._k(key))
            except self._s3.exceptions.NoSuchKey:
                return None
            return obj["Body"].read()

        return await asyncio.to_thread(_get)

    async def delete_prefix(self, prefix: str) -> None:
        def _delete() -> None:
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=self._k(prefix)):
                keys: list[ObjectIdentifierTypeDef] = [
                    {"Key": o["Key"]} for o in page.get("Contents", []) if "Key" in o
                ]
                if keys:
                    self._s3.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})

        await asyncio.to_thread(_delete)
