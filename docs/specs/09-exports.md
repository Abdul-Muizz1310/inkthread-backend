# 09 · Exports

The native graph is `inkthread.graph/1` JSON. Three exports let it leave: JSON-LD for linked-data tools,
GraphML for Gephi, yEd and Cytoscape, and a Cypher script for Neo4j, Memgraph and FalkorDB. Each export
is a pure function of the graph, so it inherits the graph's determinism: the same graph gives the same
bytes.

## 1. JSON-LD

Our own small namespace, `ink:` = `https://github.com/Abdul-Muizz1310/inkthread-backend/ns#`, mapped
onto established vocabularies (research RR-0023):

| inkthread | JSON-LD types / properties |
|---|---|
| document | `ink:Document`, `schema:CreativeWork` |
| section | `ink:Section`, `doco:Section` |
| paragraph | `ink:Paragraph`, `doco:Paragraph` |
| list_item | `ink:ListItem`, `doco:Paragraph` |
| table | `ink:Table`, `doco:Table` |
| note | `ink:Note`, `doco:Footnote` |
| definition | `ink:Definition`, `doco:Glossary` |
| term | `ink:Term`, `schema:DefinedTerm`, `skos:Concept` |
| external | `ink:External`, `schema:CreativeWork` |
| `contains` | `po:contains` |
| `continues` | `ink:continues` |
| `cites_note` | `ink:citesNote` |
| `defines` | `ink:defines` |
| `uses_term` | `ink:usesTerm` (a kind of `schema:mentions`) |
| `refers_to` | `dcterms:references` |
| `cites_external` | `cito:cites` |
| `governs`, `qualifies`, `overrides`, `illustrates` | `ink:governs`, `ink:qualifies`, `ink:overrides`, `ink:illustrates` |
| roles | `ink:role` with values `ink:role/<role>` (obligation, permission and prohibition read as LegalRuleML's deontic operators) |
| page region | `prov:wasDerivedFrom` → an `oa:SpecificResource` whose `oa:hasSelector` is an `oa:FragmentSelector` with value `page=<n>&viewrect=<l>,<t>,<w>,<h>` conforming to RFC 8118 |

Each node is one object with `@id` = `ink:node/<id>` and its direct relations as properties. Each
edge is also an `ink:Assertion` object (`@id` = `ink:edge/<id>`), so its metadata stays attached: `ink:subject`,
`ink:predicate`, `ink:object`, `ink:basis`, `ink:tier`, `ink:method`, and `ink:evidence` as an
`oa:TextQuoteSelector` (`oa:exact`) plus an `oa:TextPositionSelector` (`oa:start`, `oa:end`). The
`@context` is inline, so the export needs no network.

## 2. GraphML

One `<graph edgedefault="directed">`. Node attributes: `kind`, `label`, `text`, `roles`
(comma-joined), `tier`, `score`, `page` (first region's page, or empty), `section`. Edge attributes:
`type`, `family`, `basis`, `method`, `tier`, `score`, `label`, `evidence`. Every attribute is declared
once as a `<key>` with its type. Text is XML-escaped, and characters XML 1.0 forbids are dropped.

## 3. Cypher

A script of `MERGE` statements that is safe to run twice:
1. `CREATE CONSTRAINT inkthread_id IF NOT EXISTS FOR (n:Inkthread) REQUIRE n.id IS UNIQUE;`
2. One `MERGE (n:Inkthread:<Kind> {id: "…"}) SET n += {…};` per node. Kind labels are Document,
   Section, Paragraph, ListItem, Table, Note, Definition, Term and External.
3. One `MATCH (a:Inkthread {id: "…"}), (b:Inkthread {id: "…"}) MERGE (a)-[r:<TYPE> {id: "…"}]->(b)
   SET r += {…};` per edge. Types are the edge type in upper case.

String literals escape the backslash, the double quote and the newline, carriage return and tab
characters. List properties (roles) are Cypher lists of strings.

## 4. Test cases

- T-EX-1 JSON-LD: every node and every edge appears once with its `@id`; each edge is an
  `ink:Assertion` with subject, predicate and object; expanding the document with pyld (inline context,
  no network) yields at least one triple per node.
- T-EX-2 JSON-LD: a region becomes an RFC 8118 fragment selector whose numbers match the bbox.
- T-EX-3 GraphML parses with networkx, which reports the same node and edge counts and the same
  attributes.
- T-EX-4 GraphML: a text holding `<`, `&`, a quote and a form-feed character is escaped, and the
  form-feed is dropped.
- T-EX-5 Cypher: one constraint, one `MERGE` per node and one per edge.
- T-EX-6 (property) For any string, the Cypher literal the exporter writes reads back to the same
  string under Cypher's escape rules (a test-side decoder).
- T-EX-7 Each exporter returns identical bytes for the same graph.
