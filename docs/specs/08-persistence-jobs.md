# 08 · Persistence, blobs, jobs and the reader process

## 1. Tables (Postgres; Alembic migration `0001_initial`)

| table | columns | constraints |
|---|---|---|
| `documents` | `id uuid pk`, `sha256 char(64)`, `file_name text null`, `title text null`, `page_count int`, `byte_size int`, `kind text`, `status text`, `created_at`, `updated_at`, `expires_at timestamptz null` | `sha256` unique; `kind in (sample, upload)`; `status in (queued, processing, ready, failed)`; `page_count > 0`; `byte_size > 0` |
| `jobs` | `id uuid pk`, `document_id uuid`, `status text`, `stage text null`, `attempt int`, `created_at`, `started_at`, `finished_at`, `error_code text null`, `error_message text null`, `stages jsonb`, `llm jsonb` | fk → documents `on delete cascade`; `status in (queued, running, succeeded, failed)`; index `(status, created_at)` |
| `job_events` | `job_id uuid`, `seq int`, `type text`, `payload jsonb`, `created_at` | pk `(job_id, seq)`; fk → jobs `on delete cascade` |
| `graphs` | `document_id uuid pk`, `schema_version text`, `graph_hash char(64)`, `graph jsonb`, `ops jsonb`, `created_at` | fk → documents `on delete cascade` |
| `llm_calls` | `id bigserial pk`, `job_id uuid null`, `task text`, `model text null`, `request_key char(64)`, `cached bool`, `status text`, `http_status int null`, `latency_ms int`, `prompt_tokens int null`, `completion_tokens int null`, `created_at` | fk → jobs `on delete set null`; index `(created_at)` |
| `llm_responses` | `request_key char(64) pk`, `task text`, `served_model text`, `response jsonb`, `created_at` | — |

Every timestamp is `timestamptz` (a parity test checks ORM and migration agree; see
`lesson-sqlite-hides-postgres-defects`). Tests run against real Postgres (Testcontainers), never SQLite.

The engine uses `pool_pre_ping=True` and `pool_recycle=300`, and normalises Neon URLs (`postgres://`
→ `postgresql+asyncpg://`, `sslmode=require` → `ssl=require`, `channel_binding` dropped).

## 2. Blobs

`BlobStore` port: `put(key, data, content_type)`, `get(key) → bytes | None`, `delete_prefix(prefix)`.
Adapters: `LocalBlobStore(root)` for development and tests, `R2BlobStore` (S3 API via boto3 in a
worker thread, under `R2_PREFIX`), and `PgBlobStore` (rows of a `blobs` table, migration `0002`).
Production runs on `PgBlobStore` since 2026-10-14, when the portfolio's R2 credentials answered
`Unauthorized`; R2 returns by setting `BLOB_STORE=r2` once they are replaced. Under `PgBlobStore`
the retention sweep also enforces `BLOB_BUDGET_MB` (300): past it, the oldest uploads go first, and
samples are never evicted (Neon's free branch holds 0.5 GB). Keys are content-addressed by the PDF's sha256:

| key | what |
|---|---|
| `pdf/<sha>.pdf` | the uploaded bytes |
| `pages/<sha>/<n>.png` | page `n` rendered at 2× (144 dpi) |
| `pages/<sha>/<n>.json` | page `n`'s word geometry (spec 02 § 9) |

## 3. The reader process

`read_in_child(pdf_bytes, timeout_s) → ReadResult` runs in a fresh `spawn` process, one at a time
(D-6). The child:
1. sets `RLIMIT_AS` to `READ_MEMORY_LIMIT_MB` when set (Linux only);
2. calls `inkgrid.read(bytes)` and `inkgrid.verify(doc, bytes)`;
3. renders every page to PNG with PyMuPDF at 2×;
4. sends back `{document_json, report_json, pngs}` through a pipe.

On timeout the parent terminates the child and the job fails `read_timeout`. Errors come back as codes
rather than exceptions: `PasswordRequired` → `pdf_encrypted`, `PdfOpenError` → `pdf_unreadable`,
anything else → `reader_failed`. A reading with no content block (every page lacks a text layer, or
the PDF is blank) fails the job with `no_text_layer`, because inkthread does not OCR.

## 4. Jobs

**Enqueue.** `ingest` creates or finds the document by sha256, stores the PDF blob, and inserts a
`queued` job unless a queued or running one exists.

**Run.** A `JobRunner` task starts in the app's lifespan:
1. It claims the oldest queued job with `UPDATE … WHERE id = (SELECT id FROM jobs WHERE status =
   'queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING …`, so two instances can
   never claim one job.
2. It runs the pipeline and, for every event, appends a `job_events` row and then broadcasts it.
3. On success it writes `graphs` and the geometry blobs, sets the document `ready` and the job
   `succeeded`, then emits `done`. The job row records per-stage timings, the reasons for any skipped
   stages, and model request counts.
4. On failure it records the error code, sets both rows `failed`, and emits `failed`.

The runner sleeps on an event that an upload sets, and polls every 5 s. A whole job has a deadline of
`JOB_TIMEOUT_S` (900).

**Reaper.** At startup, a `running` job left by a crash goes back to `queued` with `attempt + 1`, or to
`failed` with `interrupted` once `attempt` reaches 2.

**Retention.** Every hour, uploads whose `expires_at` (created + `RETENTION_DAYS`, 7) has passed are
deleted with their blobs. Samples never expire.

## 5. Samples

`samples/manifest.toml` lists each sample PDF (committed: public-domain US government documents)
with its source URL and sha256. `python -m inkthread.cli seed` uploads each one as `kind = sample`
and runs it through the normal pipeline. `samples/answers/*.json` holds the recorded model answers the
samples used. Seeding imports them first, so a fresh database replays the samples with zero model
calls; `--record` runs live and exports any new answers.

## 6. Test cases

Integration (Postgres via Testcontainers):
- T-PJ-1 `alembic upgrade head` then `downgrade base` runs clean; every timestamp column is tz-aware in
  both the ORM and the migration.
- T-PJ-2 A second document with the same sha256 violates the unique constraint; deleting a document
  cascades to its jobs, events and graph, and sets its `llm_calls.job_id` to null.
- T-PJ-3 Two concurrent `claim_next` calls claim two different jobs, never the same one.
- T-PJ-4 Event `seq` is unique per job; appending reads back in order.
- T-PJ-5 The daily request count includes only today's uncached attempts (UTC).
- T-PJ-6 The reaper requeues a running job once, then fails it as `interrupted`.
- T-PJ-7 Retention deletes expired uploads and their blobs, and keeps samples and unexpired uploads.

Reader (real child process, synthetic PDFs):
- T-PJ-8 A two-page PDF comes back with a document, a report and two PNGs.
- T-PJ-9 An encrypted PDF → `pdf_encrypted`; garbage after `%PDF-` → `pdf_unreadable`.
- T-PJ-10 A child that exceeds the timeout is terminated, and the result is `read_timeout`.
- T-PJ-11 An image-only PDF fails the job with `no_text_layer`.

Composed (the whole flow, CI-mandatory):
- T-PJ-12 Upload a synthetic PDF through the API. The runner processes it with a replay-mode model, and
  then:
  - the event stream ends with `done`;
  - `GET /graph` returns a graph that passes the explain gate;
  - the page PNG and geometry are served.
- T-PJ-13 The same upload replayed from recorded answers yields the same `graph_hash` with zero model
  requests (G7).
- T-PJ-14 Blob stores: local and a fake S3 both round-trip `put`/`get` and delete by prefix.
