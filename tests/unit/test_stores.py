"""Spec 08 § 2: samples and uploads never share a store (T-PJ-15)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inkthread.storage.blobs import LocalBlobStore
from inkthread.storage.stores import Stores


def test_each_kind_has_its_own_store(tmp_path: Path) -> None:
    samples, uploads = LocalBlobStore(tmp_path / "s"), LocalBlobStore(tmp_path / "u")
    stores = Stores(samples=samples, uploads=uploads)
    assert stores.for_kind("sample") is samples
    assert stores.for_kind("upload") is uploads


def test_an_unknown_kind_is_refused(tmp_path: Path) -> None:
    stores = Stores(samples=LocalBlobStore(tmp_path), uploads=LocalBlobStore(tmp_path))
    with pytest.raises(ValueError, match="kind"):
        stores.for_kind("draft")
