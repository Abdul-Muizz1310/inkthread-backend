# 11 · The reading: inkgrid's tables and verification, kept per document

The graph says how a document's parts relate. Some callers want what inkgrid itself read: each table
as rows and Markdown, and whether a second PDF engine agreed with the text (bastion's dossier quotes
both). inkthread keeps that per document, derived while the job runs, and serves it at
`GET /documents/{id}/reading` (interface I-3 of the 2026-10-20 rollout plan).

## 1. What is kept

When the reader returns, the parent derives a `ReadingDigest` from inkgrid's `Document` and
`VerificationReport` (`inkthread.reader.digest`, the only module besides `adapt` that reads inkgrid's
types):

| field | from |
|---|---|
| `inkgrid_version` | `Document.producer.inkgrid`, the version that read the PDF |
| `verification.ok` | `VerificationReport.ok`: no defect (advisories do not count) |
| `verification.engine` | `"pdfium <pdfium> (pypdfium2 <pypdfium2>)"`, from the report's `verifier` |
| `verification.checked` | pages the second engine compared (`status == "verified"`) |
| `verification.disagreements` | the number of defects |
| `verification.defects` | every defect in report order: `{code, page, message}`, `message` = its `detail` |
| `tables` | every table block in reading order: `{id, page, bbox, header_rows, rows, markdown}` |
| `findings` | inkgrid's document findings: `{code, severity, page}` (`page` null when document-wide) |

A table's `id` is its inkgrid block id (`b<n>`); `page` and `bbox` are its one region (PDF points,
top-left origin); `rows` are `Table.to_rows()`'s text, dense, a merged cell's text repeated at every
position it covers; `markdown` is `Table.to_markdown()` (GFM, a merged cell's text once).

**Invariants**, enforced when a digest is built (a digest that breaks one is a bug, never stored):
`disagreements == len(defects)`; `ok` is true exactly when there are no defects; every row of a
table has the same length; `header_rows <= len(rows)`; table ids
are unique.

**Node ids.** When the job succeeds, the runner pairs each table with the graph's `table` node whose
`source.blocks` cites the table's block; a table the structure stage set aside (a table of contents,
say) has `node_id: null`.

**Storage.** The `readings` table (migration `0003_readings`), one row per document, written in the
same transaction as the graph and replaced with it on reprocess. It holds derived data only: no PDF
bytes and no page images. An upload's reading goes with its document when the upload expires
(cascade), so DR-0029 holds: uploads are processed, not kept.

## 2. The route

`GET /documents/{id}/reading` →

```json
{ "schema": "inkthread.reading/1", "document_id": "…", "doc_sha256": "…", "inkgrid_version": "0.2.0",
  "verification": { "ok": true, "engine": "pdfium … (pypdfium2 …)", "checked": 15, "disagreements": 0,
                    "defects": [] },
  "tables": [ { "id": "b12", "node_id": "…", "page": 3, "bbox": [72.0, 96.5, 540.0, 300.2],
                "header_rows": 1, "rows": [["Fee", "Amount"], ["Filing", "$350"]],
                "markdown": "| Fee | Amount |\n| --- | --- |\n| Filing | $350 |" } ],
  "findings": [ { "code": "hidden_text", "severity": "warning", "page": 2 } ] }
```

- `404 not_found` for an unknown document; `422 validation_error` for a malformed id.
- `409 graph_not_ready` while the document has no reading: it is queued, processing or failed, or it
  was processed before readings were kept (until it is reprocessed).
- During a reprocess the previous reading is served, as the graph is.
- `Cache-Control: public, max-age=300`, as the graph.
- Protected exactly as the graph is (platform contract v2 on the `contract-v2` branch).

## 3. Test cases

Digest (real inkgrid, synthetic PDFs):
- T-RD-1 A PDF with one ruled table gives one table: its block id, page 1, the region's bbox, its
  header rows, rectangular rows equal to `Table.to_rows()`'s text, and `Table.to_markdown()`.
- T-RD-2 A PDF with no table gives `tables: []`; a clean report gives `ok: true`, `disagreements: 0`,
  `defects: []` and `checked` equal to the verified pages.
- T-RD-3 A report with defects gives `ok: false`, `disagreements == len(defects)`, each defect's code,
  page and detail as `message`; advisories are not counted.
- T-RD-4 `inkgrid_version` is the producer's; `engine` names PDFium and pypdfium2 with their versions.
- T-RD-5 A digest whose `disagreements` differs from its defects, whose `ok` disagrees with them,
  whose rows are ragged, whose header rows exceed its rows, or whose table ids repeat is refused at
  construction.

Node ids (pure):
- T-RD-6 A table cited by a `table` node gets that node's id; a table no node cites gets `null`.

Persistence (Postgres):
- T-RD-7 Migration `0003` creates `readings`; `upgrade head` twice is a no-op; `downgrade 0002` drops
  it; its timestamp is tz-aware in the ORM and the migration.
- T-RD-8 Saving a reading twice for one document replaces it; deleting the document deletes its
  reading.

Route (composed flow, CI-mandatory):
- T-RD-9 An upload processed through the API serves `/reading` with `schema`, `document_id`,
  `doc_sha256`, `inkgrid_version`, the verification summary, its tables (with node ids) and findings.
- T-RD-10 `/reading` for an unknown document → 404; a malformed id → 422; a document whose job has
  not succeeded → 409 `graph_not_ready`.
- T-RD-11 The runner writes no reading for a failed job, and a reprocessed document's reading is
  replaced when the new job succeeds.

