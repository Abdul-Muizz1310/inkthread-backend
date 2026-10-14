"""Spec 09 § 4: JSON-LD, GraphML and Cypher exports (T-EX-1…7)."""

from __future__ import annotations

import io
import json
import re
from typing import Any

import networkx as nx
import pytest
from finalize_sample import sample
from hypothesis import given
from hypothesis import strategies as st
from pyld import jsonld

from inkthread.domain.exports.cypher import cypher_string, to_cypher
from inkthread.domain.exports.graphml import to_graphml
from inkthread.domain.exports.jsonld import CONTEXT, to_jsonld
from inkthread.domain.finalize import finalize
from inkthread.domain.model import Graph, Node

INK = "https://github.com/Abdul-Muizz1310/inkthread-backend/ns#"


def build() -> Graph:
    s = sample()
    return finalize(s.draft, s.reading, inkgrid_version="0.1.0", prompts_hash="ph", models={}).graph


GRAPH = build()


def no_network(url: str, options: Any = None) -> Any:
    raise AssertionError(f"pyld tried to load {url}")


# JSON-LD ----------------------------------------------------------------------------------------


def test_jsonld_has_every_node_and_edge() -> None:  # T-EX-1
    doc = json.loads(to_jsonld(GRAPH))
    assert doc["@context"] == CONTEXT
    ids = [o["@id"] for o in doc["@graph"]]
    for n in GRAPH.nodes:
        assert ids.count(f"ink:node/{n.id}") == 1
    for e in GRAPH.edges:
        assert ids.count(f"ink:edge/{e.id}") == 1
        obj = next(o for o in doc["@graph"] if o["@id"] == f"ink:edge/{e.id}")
        assert "ink:Assertion" in obj["@type"]
        assert obj["ink:subject"] == {"@id": f"ink:node/{e.source}"}
        assert obj["ink:object"] == {"@id": f"ink:node/{e.target}"}
        assert obj["ink:predicate"]
    quads = jsonld.to_rdf(doc, {"format": "application/n-quads", "documentLoader": no_network})
    for n in GRAPH.nodes:
        subject = f"<{INK}node/{n.id}>"
        assert any(line.startswith(subject + " ") for line in quads.splitlines())
    expanded = jsonld.expand(doc, {"documentLoader": no_network})
    assert len(expanded) == len(GRAPH.nodes) + len(GRAPH.edges)


def test_jsonld_region_selector() -> None:  # T-EX-2
    doc = json.loads(to_jsonld(GRAPH))
    node: Node = next(n for n in GRAPH.nodes if n.regions)
    obj = next(o for o in doc["@graph"] if o["@id"] == f"ink:node/{node.id}")
    derived = obj["prov:wasDerivedFrom"]
    assert len(derived) == len(node.regions)
    selector = derived[0]["oa:hasSelector"]
    assert selector["@type"] == "oa:FragmentSelector"
    assert selector["dcterms:conformsTo"] == {"@id": "http://tools.ietf.org/rfc/rfc8118"}
    m = re.fullmatch(r"page=(\d+)&viewrect=([^,]+),([^,]+),([^,]+),([^,]+)", selector["rdf:value"])
    assert m is not None
    x0, y0, x1, y1 = node.regions[0].bbox
    assert int(m[1]) == node.regions[0].page
    assert [float(v) for v in m.groups()[1:]] == pytest.approx([x0, y0, x1 - x0, y1 - y0])


# GraphML ----------------------------------------------------------------------------------------


def test_graphml_reads_back() -> None:  # T-EX-3
    g = nx.read_graphml(io.BytesIO(to_graphml(GRAPH)), force_multigraph=True)
    assert g.number_of_nodes() == len(GRAPH.nodes)
    assert g.number_of_edges() == len(GRAPH.edges)
    for n in GRAPH.nodes:
        attrs = g.nodes[n.id]
        assert attrs["kind"] == n.kind.value
        assert attrs["text"] == n.text
        assert attrs["label"] == n.label
        assert attrs["tier"] == n.confidence.tier.value
        assert attrs["score"] == pytest.approx(n.confidence.score)
        assert attrs["roles"] == ",".join(a.role.value for a in n.roles)
        assert attrs["section"] == (n.section or "")
        assert attrs["page"] == (str(n.regions[0].page) if n.regions else "")
    for e in GRAPH.edges:
        attrs = g.edges[e.source, e.target, e.id]
        assert attrs["type"] == e.type.value
        assert attrs["family"] == e.family.value
        assert attrs["basis"] == e.basis.value
        assert attrs["method"] == e.method
        assert attrs["evidence"] == (e.evidence.quote if e.evidence else "")


def test_graphml_escapes_and_drops_illegal_characters() -> None:  # T-EX-4
    p = next(n for n in GRAPH.nodes if n.kind.value == "paragraph")
    weird = p.model_copy(update={"label": 'a < b & "c"\x0cd'})
    g = GRAPH.model_copy(update={"nodes": tuple(weird if n.id == p.id else n for n in GRAPH.nodes)})
    raw = to_graphml(g)
    assert b"\x0c" not in raw
    assert b"&lt;" in raw
    assert b"&amp;" in raw
    back = nx.read_graphml(io.BytesIO(raw))
    assert back.nodes[p.id]["label"] == 'a < b & "c"d'


# Cypher -----------------------------------------------------------------------------------------


def test_cypher_statements() -> None:  # T-EX-5
    script = to_cypher(GRAPH).decode("utf-8")
    lines = [line for line in script.splitlines() if line.strip()]
    assert sum("CREATE CONSTRAINT" in line for line in lines) == 1
    assert lines[0].startswith("CREATE CONSTRAINT inkthread_id IF NOT EXISTS")
    merges_n = [line for line in lines if line.startswith("MERGE (n:Inkthread:")]
    merges_e = [line for line in lines if line.startswith("MATCH (a:Inkthread")]
    assert len(merges_n) == len(GRAPH.nodes)
    assert len(merges_e) == len(GRAPH.edges)
    assert all(line.endswith(";") for line in lines)
    assert any(":ListItem" in k or ":Paragraph" in k for k in merges_n)
    assert any("[r:QUALIFIES {id:" in line for line in merges_e)
    assert any('roles: ["obligation"]' in line for line in merges_n)


def decode_cypher(literal: str) -> str:
    """Read a Cypher double-quoted string literal back under Cypher's escape rules."""
    assert literal[0] == literal[-1] == '"'
    body, out, i = literal[1:-1], [], 0
    escapes = {
        "\\": "\\",
        '"': '"',
        "'": "'",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
    }
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            nxt = body[i + 1]
            if nxt == "u":
                out.append(chr(int(body[i + 2 : i + 6], 16)))
                i += 6
                continue
            out.append(escapes[nxt])
            i += 2
            continue
        assert ch != '"', "an unescaped quote ends the literal early"
        out.append(ch)
        i += 1
    return "".join(out)


@given(st.text())
def test_cypher_literal_round_trips(text: str) -> None:  # T-EX-6
    assert decode_cypher(cypher_string(text)) == text


# Determinism ------------------------------------------------------------------------------------


@pytest.mark.parametrize("export", [to_jsonld, to_graphml, to_cypher])
def test_exports_are_deterministic(export: Any) -> None:  # T-EX-7
    assert export(GRAPH) == export(build())
