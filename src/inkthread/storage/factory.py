"""Pick the blob store the configuration names (spec 08 § 2)."""

from __future__ import annotations

import boto3
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.core.config import BlobStoreKind, Settings
from inkthread.storage.blobs import BlobStore, LocalBlobStore, R2BlobStore
from inkthread.storage.pgblobs import PgBlobStore


def make_blob_store(
    settings: Settings, sessions: async_sessionmaker[AsyncSession] | None = None
) -> BlobStore:
    """A local directory, Postgres rows, or R2 through its S3 endpoint under `R2_PREFIX`."""
    if settings.blob_store is BlobStoreKind.LOCAL:
        return LocalBlobStore(settings.blob_root)
    if settings.blob_store is BlobStoreKind.POSTGRES:
        if sessions is None:
            msg = "BLOB_STORE=postgres needs the database sessions"
            raise ValueError(msg)
        return PgBlobStore(sessions)
    key_id, secret = settings.r2_access_key_id, settings.r2_secret_access_key
    if key_id is None or secret is None or not settings.r2_bucket or not settings.r2_endpoint:
        msg = "BLOB_STORE=r2 needs its credentials, bucket and endpoint"  # Settings checks too
        raise ValueError(msg)
    client = boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=key_id.get_secret_value(),
        aws_secret_access_key=secret.get_secret_value(),
        region_name="auto",
    )
    return R2BlobStore(client, settings.r2_bucket, settings.r2_prefix)
