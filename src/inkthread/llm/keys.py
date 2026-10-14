"""Request keys (spec 05 § 2): the same request always gets the same key."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from inkthread.canon import cjson, sha256_hex


def request_key(  # noqa: PLR0917 - the key's ingredients, in spec 05 § 2 order
    task: str,
    task_version: int,
    schema: Mapping[str, object],
    prompt_bytes: bytes,
    cascade: Sequence[str],
    temperature: float,
    input_payload: object,
) -> str:
    """sha256 of the canonical JSON of all that shapes the answer, except the served model."""
    return sha256_hex(
        cjson(
            {
                "task": task,
                "task_version": task_version,
                "schema_hash": sha256_hex(cjson(dict(schema))),
                "prompt_hash": hashlib.sha256(prompt_bytes).hexdigest(),
                "cascade": list(cascade),
                "temperature": temperature,
                "input": input_payload,
            }
        )
    )
