"""Spec 10 T-OPS-1: the layering rules hold in the import graph.

The domain is the pure core: no web framework, database, HTTP client, agent runtime or PDF engine.
Services never import FastAPI. Routers never reach past services into models or repositories.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "inkthread"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.add(node.module)
    return found


def modules_under(package: str) -> list[Path]:
    root = SRC / package
    return sorted(root.rglob("*.py"))


def violations(package: str, forbidden: tuple[str, ...]) -> list[str]:
    return [
        f"{path.relative_to(SRC)} imports {module}"
        for path in modules_under(package)
        for module in sorted(imported_modules(path))
        if any(module == f or module.startswith(f + ".") for f in forbidden)
    ]


def test_the_packages_exist() -> None:
    for package in ("domain", "services", "api"):
        assert (SRC / package / "__init__.py").is_file()


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        (
            "domain",
            (
                "fastapi",
                "starlette",
                "sqlalchemy",
                "httpx",
                "langgraph",
                "inkgrid",
                "pymupdf",
                "fitz",
                "boto3",
                "inkthread.reader",
                "inkthread.llm",
                "inkthread.agents",
                "inkthread.pipeline",
                "inkthread.services",
                "inkthread.repositories",
                "inkthread.models",
                "inkthread.api",
            ),
        ),
        ("services", ("fastapi", "starlette")),
        ("api", ("inkthread.models", "inkthread.repositories", "sqlalchemy")),
        ("llm", ("inkthread.agents", "inkthread.pipeline", "inkthread.domain")),
    ],
)
def test_layering(package: str, forbidden: tuple[str, ...]) -> None:
    assert violations(package, forbidden) == []
