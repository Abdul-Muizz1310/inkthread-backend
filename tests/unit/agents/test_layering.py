"""Plan Tasks 12-13: the LLM layer is generic; neither it nor the agents touch web or DB."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src" / "inkthread"


def imports(package: str) -> set[str]:
    found: set[str] = set()
    for path in (SRC / package).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
    return found


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        (
            "llm",
            ("inkthread.domain", "inkthread.agents", "inkthread.pipeline", "fastapi", "sqlalchemy"),
        ),
        ("agents", ("inkthread.pipeline", "fastapi", "starlette", "sqlalchemy", "httpx")),
    ],
)
def test_agent_layers(package: str, forbidden: tuple[str, ...]) -> None:
    bad = {m for m in imports(package) for f in forbidden if m == f or m.startswith(f + ".")}
    assert bad == set()
