"""Samples keep their files; uploads are processed, not kept (spec 08 § 2)."""

from __future__ import annotations

from dataclasses import dataclass

from inkthread.storage.blobs import BlobStore


@dataclass(frozen=True, slots=True)
class Stores:
    """The durable store for samples and the transient one for uploads, never shared."""

    samples: BlobStore
    uploads: BlobStore

    def for_kind(self, kind: str) -> BlobStore:
        """The store a document of this kind keeps its files in."""
        match kind:
            case "sample":
                return self.samples
            case "upload":
                return self.uploads
            case _:
                msg = f"unknown document kind {kind!r}"
                raise ValueError(msg)
