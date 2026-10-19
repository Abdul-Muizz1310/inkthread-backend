"""Spec 10 § 3 smoke, spec 12: what the post-deploy smoke makes of `/samples` behind the gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_health.py"
_SPEC = importlib.util.spec_from_file_location("smoke_health", _SCRIPT)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
samples_verdict = _MODULE.samples_verdict


def test_open_samples_pass_with_their_count() -> None:
    ok, line = samples_verdict(200, {"items": [{}, {}]})
    assert ok
    assert "2 items" in line


def test_a_closed_gate_passes() -> None:
    ok, line = samples_verdict(401, {"detail": "missing_platform_token"})
    assert ok
    assert "platform token" in line


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (503, {"detail": "platform_auth_unconfigured"}),
        (500, {}),
        (401, {"detail": "invalid_platform_token"}),
        (404, None),
    ],
)
def test_anything_else_fails(status: int, body: object) -> None:
    ok, _ = samples_verdict(status, body)
    assert not ok
