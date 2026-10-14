"""Spec 05 § 2: request keys (T-AG-15)."""

from __future__ import annotations

from inkthread.llm.keys import request_key

SCHEMA: dict[str, object] = {"type": "object", "properties": {"labels": {"type": "array"}}}


def key(
    *,
    task: str = "classify",
    task_version: int = 1,
    schema: dict[str, object] = SCHEMA,
    prompt_bytes: bytes = b"You label parts.",
    cascade: tuple[str, ...] = ("a/primary:free", "b/fallback:free"),
    temperature: float = 0.0,
    input_payload: object = None,
) -> str:
    payload = {"parts": [{"id": "n1", "text": "Café"}]} if input_payload is None else input_payload
    return request_key(task, task_version, schema, prompt_bytes, cascade, temperature, payload)


def test_same_request_same_key() -> None:  # T-AG-15
    assert key() == key()
    assert len(key()) == 64
    reordered = {"properties": {"labels": {"type": "array"}}, "type": "object"}
    assert key(schema=reordered) == key()


def test_each_ingredient_changes_the_key() -> None:  # T-AG-15
    base = key()
    assert key(prompt_bytes=b"You label parts!") != base
    assert key(schema={"type": "object"}) != base
    assert key(cascade=("b/fallback:free", "a/primary:free")) != base
    assert key(temperature=0.2) != base
    assert key(input_payload={"parts": []}) != base
    assert key(task_version=2) != base
    assert key(task="relate") != base
