# 06 · Confidence, provenance and the explain gate

`finalize` is pure. It scores every node, role and edge, folds the op log into a hash chain, proves the
log explains the graph, and names the graph by its content. FeeLedger's Block C principles carry over
(nothing withheld; a tier is set by the worst evidence; a score is a measurement, never the decision;
every demotion names its reason). Its check battery does not: it compared a vision reader with the text
layer, and here the text layer is the only reader.

## 1. Reasons and severities

| code | severity | on | when |
|---|---|---|---|
| `verified_text` | info | node | inkgrid's verifier checked the node's blocks and found no defect |
| `text_defect` | critical | node | the verifier reported a defect on one of the node's blocks |
| `hidden_text` | flag | node | the node holds hidden words |
| `unresolved_parts` | flag | node | the node has an unresolved call or reference |
| `explicit_inkgrid` | info | edge | made from inkgrid's links |
| `explicit_rule` | info | edge, role | made by a strong rule |
| `weak_rule` | flag | edge, role | made by a weak cue (spec 03 § 2, spec 04 § 5 positional) |
| `semantic_agent` | info | edge, role | made by an agent |
| `verifier_supported` | flag | edge, role | the verifier said supported |
| `verifier_abstained` | doubt | edge, role | the verifier abstained or left it out |
| `verifier_unavailable` | doubt | edge, role | no independent verdict (budget, failure, same model) |
| `verifier_rejected` | critical | edge, role | the verifier said unsupported |
| `target_defect` | flag | edge | the edge's target node has `text_defect` |

## 2. Tier and score

The **tier** is set by the worst severity: `info` and `advice` give A, `flag` gives B, `doubt` gives C,
`critical` gives D. A list with no reasons is A.

The **score** in [0, 1] is reported for sorting and never decides anything:

| element | score |
|---|---|
| node | 1.0, at most 0.8 with `unresolved_parts`, at most 0.7 with `hidden_text`, 0.2 with `text_defect` |
| inkgrid edge | 0.98 |
| strong rule | 0.95 |
| weak rule | 0.70 |
| agent, supported | 0.75 |
| agent, no verdict | 0.55 |
| agent, rejected | 0.25 |
| any edge with `target_defect` | at most 0.5 |

## 3. The op log

Every change to the draft is an op, appended in pipeline order:

`Op = {seq, stage, kind, target, actor, method, model, request_key, detail}`

- `kind` is one of `set_aside`, `add_node`, `add_edge`, `add_role`, `add_flag`, `add_unresolved`,
  `verdict` or `reject`.
- `target` is a block id, node id, edge id, `<node id>#<role>` or a rejected claim's key.
- Ops carry structure, never text. A span appears as offsets; a quote appears as its sha256.

**Chain.** `genesis = sha256("inkthread-oplog\x1f" + pdf_sha256 + "\x1f" + pipeline_version)` and
`op_hash = sha256(cjson(op) + "\x1f" + parent_hash)`. The graph's provenance records the head and the
count. Verifying a stored log recomputes every hash and checks the count as well as the head, so a log
cut short at the tail fails (FeeLedger X-17).

## 4. The explain gate

`explain(graph, reading, ops) → [Violation]`, run by `finalize`. Any violation fails the job with
`explain_failed`: a graph the log cannot account for is a bug, never a warning.

| check | asserts |
|---|---|
| X1 verbatim | each section's and part's text equals its source blocks' texts joined by `"\n"`; the document's text equals its title block's text, or `""` |
| X2 spans | every evidence span is valid against the node its `evidence_on` names |
| X3 regions | every section and part has at least one region |
| X4 attribution | every node, edge and role has exactly one creating op whose actor and method match its maker, and every op's target exists (in the graph, in `set_aside` or in `rejected`) |
| X5 partition | every reading block id is in exactly one node's `source.blocks` or exactly one set-aside entry |
| X6 gaps | every inkgrid footnote call with status `unresolved`, from a block that is not set aside, appears as an `Unresolved{kind: "note"}` on its node |

## 5. Determinism and the graph hash

The graph holds only what the content and the configuration determine. Timings, request counts,
cache hits and stage skip reasons live on the job (spec 08), not in the graph.

`graph_hash = sha256(cjson(graph with provenance.graph_hash set to ""))`. Two runs over the same PDF,
pipeline version, configuration and recorded answers produce the same hash (G7).

## 6. Why

`why(graph, ops, element_id)` returns the element, its maker, the rule's one-line statement from the
rule catalogue (`inkthread.domain.catalog`, one entry per rule id) or the agent task's description,
its evidence, its reasons, and the ops that touched it in order. The API serves it at
`GET /documents/{id}/why/{element_id}`.

## 7. Test cases

Tier and score:
- T-CP-1 Each row of § 1 maps to its tier in § 2; no reasons gives A; `flag` + `doubt` gives C;
  `critical` beats everything.
- T-CP-2 A node with a text defect is D with score 0.2; an edge into it gets `target_defect` and a score
  of at most 0.5.
- T-CP-3 Each agent claim state in spec 05 § 7 lands on its tier.

Op log:
- T-CP-4 The same ops give the same head; changing any op field or the order changes it.
- T-CP-5 Verification fails on a changed op, a dropped middle op, a log cut at the tail (count
  mismatch) and a wrong genesis.
- T-CP-6 No op holds a quote's text, only its sha256.

Explain:
- T-CP-7 A graph built by the pipeline from a synthetic PDF passes all six checks.
- T-CP-8 Each check fails on a graph doctored to break it: a node's text changed by a character (X1), a
  span shifted by one (X2), a part with no region (X3), an edge with no op or an op naming a missing
  target (X4), a block cited twice or never (X5), an unresolved call that does not appear (X6).

Determinism:
- T-CP-9 Building the same graph twice gives the same `graph_hash` and byte-identical JSON.
- T-CP-10 (property) The hash ignores nothing but `provenance.graph_hash`: changing any other field
  changes it.
- T-CP-11 `why` on a rule-made role returns the rule's statement and the creating op; on an agent edge,
  the model, request key and verdict.
