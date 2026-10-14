"""Command line: `inkthread export-schema`, `inkthread seed` (spec 08 § 5)."""

from __future__ import annotations

import argparse
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
    args = parser.parse_args(argv)
    if args.command == "export-schema":
        sys.stdout.write(f"wrote {export_schema()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
