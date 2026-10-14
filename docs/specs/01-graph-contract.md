# 01 · The graph contract, `inkthread.graph/1`

The graph is the product. The backend builds it, stores it as JSON and serves it; the frontend reads it.
This spec is the contract between them. The Pydantic models in `inkthread/domain/model.py` are its source
of truth, and `docs/schema/graph.schema.json` is generated from them and pinned by a test.

All models are frozen, forbid extra fields and validate on construction. Construction runs the
invariants in § 7, so an invalid graph cannot exist in memory.

## 1. Graph

| field | type | meaning |
|---|---|---|
| `schema` | `"inkthread.graph/1"` | contract version |
| `document` | `DocumentInfo` | what was read |
| `nodes` | `Node[]` | ordered by `order` |
| `edges` | `Edge[]` | ordered by (type order in § 4, source order, target order, id) |
| `set_aside` | `SetAside[]` | inkgrid blocks that are not content, verbatim, in reading order |
| `findings` | `Finding[]` | document-level findings: inkgrid's, plus the pipeline's |
| `stats` | `GraphStats` | counts and timings |
| `provenance` | `Provenance` | versions, models, the op-log head, the graph hash, rejected claims |

## 2. DocumentInfo

| field | type | rule |
|---|---|---|
| `sha256` | 64 lowercase hex | of the PDF bytes |
| `file_name` | `str \| null` | as uploaded, base name only |
| `title` | `str \| null` | the title node's text, or null |
| `title_node` | `NodeId \| null` | the node the title came from |
| `page_count` | int ≥ 1 | |
| `pages` | `{number, width, height}[]` | PDF points, unrotated, from inkgrid |

## 3. Node

| field | type | rule |
|---|---|---|
| `id` | `NodeId` | § 5 |
| `kind` | `NodeKind` | § 4 |
| `label` | str | a verbatim prefix of `text` cut at a word boundary, ≤ 80 chars; the document node's label is its title or file name |
| `label_truncated` | bool | true when `label` is shorter than `text` |
| `text` | str | verbatim (G1). `""` only for the document node |
| `order` | int ≥ 0 | reading order; the document is 0; terms and citations follow all parts, by first appearance |
| `section` | `NodeId \| null` | the section that contains it; null for the document, terms and citations |
| `depth` | int ≥ 0 | document 0, top sections 1, a part is its section's depth + 1 |
| `regions` | `{page, bbox}[]` | from inkgrid; empty only for document, term and external nodes |
| `roles` | `RoleAssignment[]` | at most one per role; sorted by role order in § 4 |
| `table` | `TableInfo \| null` | present exactly when `kind == "table"` |
| `marker` | `str \| null` | a note's label or a list item's printed label |
| `flags` | `Flag[]` | sorted by code, unique by (code, detail) |
| `hidden_spans` | `Span[]` | spans of words inkgrid marks hidden; never sent to a model |
| `unresolved` | `Unresolved[]` | calls and references that found no target |
| `confidence` | `Confidence` | § 6 |
| `source` | `{blocks: str[], keys: str[]}` | the inkgrid block ids and content keys it came from |
| `made_by` | `Maker` | § 6 |

**RoleAssignment** `{role, evidence: Span | null, made_by, basis, confidence, verdict}`.
**Span** `{start, end, quote}` with `0 ≤ start < end ≤ len(text)` and `quote == text[start:end]`.
**TableInfo** `{n_rows, n_cols, header_rows, banner_rows, source: "lattice" | "corridor", cells}`.
**CellInfo** `{row, col, row_span, col_span, text, is_header, header_path: str[], row_labels: str[],
markers: str[], carried, page, bbox}`. `header_path` and `row_labels` are verbatim cell texts (spec 02
§ 6); `bbox` is the cell's rectangle in page coordinates, or null when inkgrid gives none.
**Flag** `{code, detail}`. **Anchor** `{row, col}`: the table cell an edge's evidence sits in.
**Unresolved** `{kind: "note" | "reference", text, span: Span | null, candidates: NodeId[], reason}`.

## 3b. Edge

| field | type | rule |
|---|---|---|
| `id` | `EdgeId` | § 5 |
| `type` | `EdgeType` | § 4 |
| `family` | `EdgeFamily` | fixed by the type (§ 4) |
| `source`, `target` | `NodeId` | both exist; never equal |
| `basis` | `explicit` \| `semantic` | semantic exactly when an agent made it |
| `evidence` | `Span \| null` | the words that license the edge |
| `evidence_on` | `source` \| `target` | which node's text `evidence` is in; `target` only for precedence language printed in the yielding part (spec 04 § 7) |
| `anchor` | `Anchor \| null` | the table cell the evidence sits in |
| `label` | `str \| null` | what was matched: a marker, a term form, a reference, a citation |
| `method` | str | the rule id or agent task id that made it |
| `made_by` | `Maker` | § 6 |
| `confidence` | `Confidence` | § 6 |
| `flags` | `Flag[]` | e.g. `contested` |
| `verdict` | `Verdict \| null` | the verifier's, when it judged this edge |

**SetAside** `{block, kind: "furniture" | "toc", text, page, bbox, reason}`.
**Finding** `{code, severity, page, detail}`.
**GraphStats** `{nodes_by_kind, edges_by_type, roles, tiers}`: counts derived from the content only.
Run facts (timings, model requests, cache hits, skipped stages) live on the job (spec 08), so two runs
over the same input produce byte-identical graphs (G7).
**Provenance** `{pipeline_version, inkgrid_version, prompts_hash, models: {producer, verifier},
ops_head, ops_count, graph_hash, rejected: RejectedClaim[]}`; **RejectedClaim** `{task, request_key,
item, reason}` records a model claim that failed grounding (spec 05 § 4).

## 4. Closed vocabularies

**NodeKind:** `document`, `section`, `paragraph`, `list_item`, `table`, `note`, `definition`, `term`,
`external`.

**EdgeType**, in this order, with its family and direction:

| type | family | source → target | made by |
|---|---|---|---|
| `contains` | structure | section/document → its child | rule |
| `continues` | structure | later part → the part it continues | inkgrid |
| `cites_note` | notes | the calling part → the note | inkgrid |
| `defines` | terms | the defining part → the term | rule |
| `uses_term` | terms | a part → a term it uses | rule |
| `refers_to` | references | a part → the section, table or part it names | rule, agent |
| `cites_external` | references | a part → an outside source it names | rule |
| `governs` | logic | a lead-in or scope statement → what it governs | rule, agent |
| `qualifies` | logic | a condition, exception, method or rule → the part it qualifies | rule, agent |
| `overrides` | logic | the part that prevails → the part it displaces | rule, agent |
| `illustrates` | logic | an example → what it illustrates | agent |

**Role**, in this order: `obligation`, `permission`, `prohibition`, `condition`, `exception`,
`definition`, `computation`, `method`, `procedure`, `temporal`, `quantitative`, `scope`, `convention`,
`example`, `external_pointer`, `administrative`, `summary`, `claim`.

**Basis:** `explicit` (inkgrid or a rule) or `semantic` (an agent).

**FlagCode:** `hidden_text`, `text_defect`, `header_not_found`, `note_not_found`,
`reference_unresolved`, `multiple_definitions`, `merged_heading`, `contested`, `model_unavailable`,
`truncated_for_model`.

**ReasonCode:** `verified_text`, `text_defect`, `explicit_rule`, `explicit_inkgrid`, `weak_rule`,
`semantic_agent`, `verifier_supported`, `verifier_rejected`, `verifier_abstained`,
`verifier_unavailable`, `unresolved_parts`, `hidden_text`, `target_defect`.

**Severity:** `info`, `advice`, `flag`, `doubt`, `critical`. **Tier:** `A`, `B`, `C`, `D`.

**Actor** (in `Maker`): `inkgrid`, `rule`, `agent`, `verifier`.

## 5. Identifiers

Content-derived, so the same document read twice gets the same ids, and a node keeps its id when an
unrelated part of the document changes.

`h(parts) = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]`, `fold(s)` = Unicode
whitespace runs to one space, stripped.

| id | formula |
|---|---|
| document | `"d:" + sha256_of_pdf[:16]` |
| section | `"s:" + h(["section", *ancestor_titles, fold(text)])` |
| part | `"p:" + h([kind, *section_titles, fold(text)])` |
| term | `"t:" + h(["term", term_key])` where `term_key` is spec 04 § 2's matching key |
| external | `"x:" + h(["external", fold(citation).lower()])` |
| edge | `"e:" + h([type, source, target, method, label or ""])` |

Identical twins among sections or parts get `":2"`, `":3"` … in reading order. Two edges with the
same id are one edge: the first is kept and the duplicate is counted, never shipped twice.

## 6. Confidence and makers

**Maker** `{actor, id, model, request_key}`. `id` is a rule id (`R-…`), `inkgrid`, or an agent task
id (`A-…`). `model` and `request_key` are set exactly when `actor` is `agent` or `verifier`.

**Confidence** `{tier, score, reasons: Reason[]}`; **Reason** `{code, severity, detail}`. The tier is
set by the worst severity (spec 06 § 2); `score` in [0, 1] is reported, never decisive.

**Verdict** `{verdict: "supported" | "unsupported" | "abstain", model, request_key}`.

## 7. Invariants (checked at construction)

1. Node ids are unique; edge ids are unique.
2. Every edge's `source` and `target` are node ids in the graph, and `source != target`.
3. Exactly one `document` node, with `order == 0`, `section == null`, `depth == 0`.
4. Every `section` value names a node of kind `section` or `document`.
5. The `contains` edges form a tree rooted at the document: every section and part has exactly one
   incoming `contains`, and it comes from its `section`. Terms and externals have none.
6. Every evidence span satisfies the Span rule against its node's text: a role's against its own
   node, an edge's against the node its `evidence_on` names (source by default).
7. `table` is present exactly on table nodes; cell anchors stay inside the grid; cells tile the grid
   exactly once.
8. Every `cites_note` target is a `note`; every `defines` and `uses_term` target is a `term`; every
   `cites_external` target is an `external`; every `contains` source is a `section` or the `document`.
9. `model` and `request_key` are set on a maker exactly when its actor is `agent` or `verifier`;
   `basis == "semantic"` exactly when the maker's actor is `agent`.
10. `order` is unique among non-document nodes and increases along `nodes`.

## 8. Test cases

Pass:
- T-GC-1 A minimal graph (document, one section, one paragraph, one `contains` edge each) builds and
  round-trips through JSON to an equal model.
- T-GC-2 The JSON Schema generated from the model equals the committed `docs/schema/graph.schema.json`.
- T-GC-3 Part ids are stable: the same kind, section titles and text give the same id; a whitespace
  change inside the text gives the same id; a word change gives a different id.
- T-GC-4 Twin parts in one section get `:2` and `:3` in reading order.
- T-GC-5 Two edges with the same (type, source, target, method, label) collapse to one.
- T-GC-6 Labels: a 200-char text yields a label ≤ 80 chars that is a prefix of the text, cut at a
  word boundary, with `label_truncated` true; a short text yields itself with `label_truncated` false.
- T-GC-7 (property) For any text and any valid `(start, end)`, `Span.of(text, start, end).quote ==
  text[start:end]`.

Fail (construction raises):
- T-GC-8 Duplicate node id.
- T-GC-9 An edge to a node that does not exist.
- T-GC-10 A self-loop edge.
- T-GC-11 No document node, or two.
- T-GC-12 A part with two incoming `contains` edges, or none.
- T-GC-13 A span whose quote is not `text[start:end]`, or whose bounds fall outside the text.
- T-GC-14 A `cites_note` edge whose target is a paragraph.
- T-GC-15 A table node without `table`, or a paragraph with one.
- T-GC-16 A semantic edge whose maker is a rule, or an agent maker with no model.
- T-GC-17 An unknown kind, role, edge type or flag code.
- T-GC-18 Cells that overlap or leave a grid slot uncovered.
