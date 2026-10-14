"""inkthread: a born-digital PDF as a knowledge graph of its parts and the threads between them."""

from __future__ import annotations

__version__ = "0.1.0"

#: Bumped whenever the pipeline's output can change for the same input (spec 06 § 5).
PIPELINE_VERSION = "1.0.0"

#: The graph contract this service emits (spec 01).
GRAPH_SCHEMA = "inkthread.graph/1"
