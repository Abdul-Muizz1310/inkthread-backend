"""Canonical JSON and hashing, shared by the op log, request keys and the graph hash."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def cjson(obj: Any) -> str:  # noqa: ANN401 - any JSON-able value
    """Canonical JSON: sorted keys, no whitespace, UTF-8 characters kept as they are."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    """SHA-256 of UTF-8 text, as hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
