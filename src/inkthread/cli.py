"""Command line: `inkthread export-schema`, `inkthread seed` (spec 08 § 5)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from inkthread.domain.model import Graph

SCHEMA_PATH = Path("docs/schema/graph.schema.json")


def export_schema(path: Path = SCHEMA_PATH) -> Path:
    """Write the graph contract's JSON Schema, the file T-GC-2 pins."""
    schema = Graph.model_json_schema(by_alias=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="inkthread")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("export-schema", help="write docs/schema/graph.schema.json")
    sub.add_parser("seed", help="ingest samples/ as sample documents and wait for them")
    answers = sub.add_parser("answers", help="move recorded model answers in or out of samples/")
    answers.add_argument("direction", choices=["import", "export"])
    args = parser.parse_args(argv)
    if args.command == "export-schema":
        sys.stdout.write(f"wrote {export_schema()}\n")
    elif args.command == "seed":
        return asyncio.run(_seed())
    elif args.command == "answers":
        return asyncio.run(_answers(args.direction))
    return 0


SAMPLES = Path("samples")


async def _seed() -> int:
    from inkthread.main import create_app  # noqa: PLC0415 - heavy import only for this command
    from inkthread.services.samples import import_answers, load_manifest, seed  # noqa: PLC0415

    app = create_app()
    async with app.router.lifespan_context(app):
        services = app.state.services
        loaded = await import_answers(services.sessions, SAMPLES)
        sys.stdout.write(f"imported {loaded} recorded answers\n")
        result = await seed(services.ingest, services.documents, load_manifest(SAMPLES))
    for title, status in result.items():
        sys.stdout.write(f"{status:8} {title}\n")
    return 0 if all(v == "ready" for v in result.values()) else 1


async def _answers(direction: str) -> int:
    from inkthread.core.config import get_settings  # noqa: PLC0415
    from inkthread.core.db import make_engine, make_sessions  # noqa: PLC0415
    from inkthread.services.samples import export_answers, import_answers  # noqa: PLC0415

    engine = make_engine(get_settings().database_url)
    try:
        sessions = make_sessions(engine)
        fn = import_answers if direction == "import" else export_answers
        n = await fn(sessions, SAMPLES)
    finally:
        await engine.dispose()
    sys.stdout.write(f"{direction}ed {n} answers\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
