# 07 · HTTP API and the event stream

Routers are HTTP only: they parse, call one service, and map domain errors to the envelope. Routes are
unversioned (D-8); the graph carries its own version.

## 1. Errors

Every error body is `{"error": "<code>", "message": "<one sentence>", "detail": <object|null>}`.
Domain errors carry their status and code; FastAPI's validation errors map to `422 validation_error`
with the field errors in `detail`; an unexpected exception maps to `500 internal_error` with no detail
(the request id is in the response header and the log).

| status | code | when |
|---|---|---|
| 400 | `empty_file` | the upload has no bytes |
| 401 | `admin_token_required` | an admin route without `X-Admin-Token` |
| 403 | `admin_token_invalid` | a wrong token (constant-time compare) |
| 404 | `not_found` | unknown document, job, page or element |
| 409 | `graph_not_ready` | the graph is asked for before the job succeeds |
| 410 | `upload_not_kept` | an upload's page image or geometry, or reprocessing it, after its files are gone (spec 08 § 2) |
| 413 | `file_too_large` | over `MAX_UPLOAD_BYTES` |
| 415 | `not_a_pdf` | no `%PDF-` in the first 1,024 bytes |
| 422 | `pdf_unreadable`, `pdf_encrypted`, `too_many_pages`, `validation_error` | the PDF cannot be opened, needs a password, or exceeds `MAX_PAGES` |
| 429 | `rate_limited` | over the upload rate; `Retry-After` set |
| 503 | `queue_full`, `admin_disabled`, `service_unavailable` | the queue is full; no admin token is configured (admin routes fail closed); the database is down |

## 2. Routes

| method and path | does | success |
|---|---|---|
| `POST /documents` | multipart field `file`: validate, hash, store, enqueue | `202 {document, job}` with `Location: /jobs/{id}`; `200 {document, job, deduplicated: true}` when the same bytes were already uploaded and are queued, running or ready |
| `GET /samples` | the curated sample documents | `200 {items: DocumentOut[]}` |
| `GET /documents/{id}` | one document with its latest job | `200 DocumentOut` |
| `GET /documents/{id}/graph` | the graph (spec 01) | `200`, `ETag: "<graph_hash>"`, `Cache-Control: public, max-age=300`; `304` on a matching `If-None-Match` |
| `GET /documents/{id}/graph.{format}` | an export (spec 09): `jsonld`, `graphml`, `cypher` | `200` with its media type and `Content-Disposition: attachment` |
| `GET /documents/{id}/pages/{n}.png` | the rendered page | `200 image/png`, `Cache-Control: public, max-age=31536000, immutable` |
| `GET /documents/{id}/pages/{n}/geometry` | the page's word geometry (spec 02 § 9) | `200 [{node, start, end, bbox}]`, immutable cache |
| `GET /documents/{id}/why/{element_id}` | attribution (spec 06 § 6) | `200 Why` |
| `GET /jobs/{id}` | job status | `200 JobOut` |
| `GET /jobs/{id}/events` | the event stream (§ 3) | `200 text/event-stream` |
| `DELETE /documents/{id}` | admin: delete a document and its blobs | `204` |
| `POST /documents/{id}/reprocess` | admin: run the pipeline again | `202 {document, job}` |
| `GET /health`, `GET /version`, `GET /metrics` | spec 10 | |

Uploads are not listed anywhere: an uploaded document is reachable only by its id (a UUID4). Only
samples are listed.

`DocumentOut` = `{id, sha256, file_name, title, page_count, kind: "sample" | "upload", status:
"queued" | "processing" | "ready" | "failed", created_at, expires_at, stats, latest_job}`.
`JobOut` = `{id, document_id, status: "queued" | "running" | "succeeded" | "failed", stage,
created_at, started_at, finished_at, error, llm: {requests, cached, failed, rejected}, stages:
[{name, status, ms, reason}]}`.

## 3. Events

`GET /jobs/{id}/events` sends `text/event-stream` with `Cache-Control: no-cache, no-transform` and
`X-Accel-Buffering: no`. Every persisted event has an `id:` (its sequence number, from 1), an
`event:` name and one JSON `data:` line.

| event | data | persisted |
|---|---|---|
| `stage` | `{stage, status: "started" \| "completed" \| "skipped" \| "failed", ms, reason, counts}` | yes |
| `delta` | `{stage, nodes: NodeSketch[], edges: EdgeSketch[], roles: RoleSketch[], flags: FlagSketch[]}` | yes |
| `llm` | `{task, model, cached, ok, status, ms}` | yes |
| `done` | `{document_id, graph_hash, stats}` | yes |
| `failed` | `{code, message}` | yes |
| `ping` | `{t}` every 15 s | no |

Sketches are small on purpose: they animate the build. When `done` arrives, the client fetches the full
graph.
- `NodeSketch` = `{id, kind, label, section, depth, order, page}`
- `EdgeSketch` = `{id, type, source, target, basis}`
- `RoleSketch` = `{node, role, basis}`
- `FlagSketch` = `{node, code}`

**Replay and resume.** A `Last-Event-ID` header (or `?after=N`) replays persisted events with
`id > N`, then streams live ones. For a finished job the stream replays everything, ends with `done`
or `failed`, and closes. The persisted log is therefore also the build animation for any document, any
time later.

**No gaps, no doubles.** The stream subscribes to the job's live broadcast **before** it reads the
persisted log, buffers live events while replaying, and drops any live event whose id it has already
sent. A stream lasts at most 10 minutes; the client reconnects with `Last-Event-ID`.

## 4. Limits and headers

- Uploads: `MAX_UPLOAD_BYTES` (15 MB), checked while streaming the body, so an oversized upload is cut
  off without being read whole.
- `%PDF-` must appear in the first 1,024 bytes.
- Page count and encryption are read with pypdfium2 in a worker thread, behind one process-wide lock.
- 5 uploads per client IP per hour, a sliding window in memory (one instance).
- `X-Request-Id` is echoed or generated on every response.
- CORS allows `CORS_ORIGINS` only, with methods GET, POST, DELETE and OPTIONS. It allows the request
  headers `content-type`, `x-admin-token` and `last-event-id`, and exposes `location`, `etag`,
  `retry-after` and `x-request-id`.

## 5. Test cases

Upload:
- T-API-1 A valid PDF returns 202 with a document, a job and a Location header; the job is queued.
- T-API-2 The same bytes again return 200 with `deduplicated: true` and the same document id.
- T-API-3 After a failed job, the same bytes enqueue a new job (202).
- T-API-4 Empty file → 400 `empty_file`; a PNG → 415 `not_a_pdf`; 16 MB → 413 `file_too_large`
  without reading the whole body; an encrypted PDF → 422 `pdf_encrypted`; 41 pages → 422
  `too_many_pages`; truncated bytes after `%PDF-` → 422 `pdf_unreadable`.
- T-API-5 The sixth upload from one IP within an hour → 429 with `Retry-After`; another IP is not
  limited.
- T-API-6 With 10 jobs queued, the next upload → 503 `queue_full`.

Reads:
- T-API-7 `GET /documents/{id}` for an unknown id → 404; for a malformed id → 422.
- T-API-8 `GET /graph` while processing → 409; when ready → 200 with ETag; a matching `If-None-Match`
  → 304.
- T-API-9 Each export format returns its media type and a filename; an unknown format → 404.
- T-API-10 A page PNG within range → 200 immutable; page 0 or past the end → 404.
- T-API-11 `GET /samples` lists samples only, never uploads.
- T-API-12 `why` on a known element → 200; on an unknown one → 404.

Admin:
- T-API-13 DELETE without a token → 401; with a wrong one → 403; with no `ADMIN_TOKEN` configured
  → 503 `admin_disabled` even with a header; with the right one → 204, and the blobs are gone.
- T-API-14 Reprocess a sample with the right token → 202 and a new job (an upload → `410`, T-PJ-19).

Events:
- T-API-15 A finished job's stream replays every event in order, ends with `done` and closes.
- T-API-16 `Last-Event-ID: 3` replays from 4.
- T-API-17 A stream opened mid-run receives every event exactly once: no event persisted between
  subscribe and replay is lost or doubled.
- T-API-18 An unknown job → 404 before any stream starts.

Envelope:
- T-API-19 Every 4xx and 5xx body has `error` and `message`; a 500 carries no stack trace.
- T-API-20 Every response has `X-Request-Id`; an incoming one is echoed.
- T-API-21 CORS: an allowed origin gets the headers; any other origin gets none.
