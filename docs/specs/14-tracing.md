# 14 · Tracing: Langfuse v4 through Python SDK v5

Every job is one Langfuse trace whose tree reads like the run: which stage took the time, what each
agent asked which model, what it cost in tokens, which answers came from the record, and where it
failed. The target is the Langfuse v4 platform (observations-first; Langfuse Cloud is v4-only from
2026-11-16) through **Python SDK v5** (`langfuse>=5.0.4,<6`), the SDK Langfuse names for Cloud.
The `llm_calls` table and the `llm` stream events (spec 05 § 6, spec 07) stay as they are: they are
the product's own record; the trace is the operator's view.

## 1. The client (`inkthread.core.tracing`)

| variable | default | rule |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | unset | both set → tracing on; either unset or blank → every observation is a no-op and nothing is exported |
| `LANGFUSE_BASE_URL` | the SDK's (EU Cloud) | the project is on US Cloud: `https://us.cloud.langfuse.com` |

- `create_app` calls `configure(settings)` once, with the settings it validated: with both keys it
  installs a client built from them; without, it leaves tracing off. Until then the process has one
  no-op client, so code that runs outside an app (the unit tier, scripts) traces nothing.
  **Environment** = `APP_ENV`, whose closed set (`development`, `test`, `production`) is already
  valid for Langfuse. **Release** is left to the SDK, which reads `RENDER_GIT_COMMIT` on Render.
- Export runs in the SDK's background batches; nothing flushes on a job's path. The app's lifespan
  calls `shutdown()` (flush, then stop) when it ends, which also covers `inkthread seed`.
- Instrumentation is manual. The LangChain `CallbackHandler` was tried in the paper-trail rollout and
  rejected: model calls made over `httpx` inside a node did not become children of the node's span.

## 2. Trace shape

One trace per job run (`JobRunner._run`). Names are stable and verb-first: evaluators, dashboards
and saved filters target them, so run-specific values live in metadata, never in a name.

| step | type | name |
|---|---|---|
| the job | `chain` | `build-document-graph` |
| `read` | `chain` | `read-pdf` |
| `structure` | `chain` | `build-structure` |
| `classify_rules` | `chain` | `classify-by-rules` |
| `classify_agent` | `agent` | `classify-parts` |
| `link_rules` | `chain` | `link-by-rules` |
| `relate_agent` | `agent` | `relate-parts` |
| `verify_agent` | `evaluator` | `verify-claims` |
| `finalize` | `chain` | `finalize-graph` |
| a recorded-answer lookup (spec 05 § 2) | `retriever` | `recall-answer` |
| one HTTP attempt (spec 05 § 6) | `generation` | the task: `classify`, `relate`, `verify` |

The deterministic stages are `chain`s, links that pass the draft on. The classify and relate stages
are `agent`s: a model decides what to add. `verify-claims` is an `evaluator`, the most specific type:
a second model judging the first one's claims (supported, unsupported, abstain) is an LLM-as-a-judge
inside the pipeline. A lookup in `llm_responses` only reads, so it is a `retriever`.

Each stage nests under `build-document-graph`; `recall-answer` and the generations nest under the
agent stage that ran them, in order.

### Stage observations

`metadata`: `stage` (the internal name), `status` (`completed`, `skipped`, `failed`), `reason` and
the stage's counts (`pages`, `blocks`, `nodes`, `set_aside`, `edges`, `accepted`, `rejected`).
Level: `failed` → `ERROR` with the failure code as `status_message`; skipped or answered with a
batch-level reason `budget`, `model_unavailable` or `invalid_answer` → `WARNING` with the reason;
`no_input`, `disabled` and `replay_miss` are expected and stay `DEFAULT`.

### Generations

One per HTTP attempt, never one wrapping the cascade:

- `model`: the slug asked. `model_parameters`: `temperature`, `max_tokens`, `response_format`
  (`json_schema`, `json_object` or `none`) and `reasoning_effort`.
- `input`: the messages sent. `output`: the assistant message, with OpenRouter's `reasoning` text
  when the model returned one; a failed attempt that got a reply (`no_json`, `length`) keeps it, which
  is what debugging it needs.
- `metadata`: `task`, `attempt` (1-based per model), `provider` (OpenRouter's upstream provider).
- `usage_details` from OpenRouter's `usage`, as **exclusive** buckets (Langfuse adds buckets up):
  `input = prompt_tokens − cached_tokens`, `input_cached_tokens` (when > 0),
  `output = completion_tokens − reasoning_tokens`, `output_reasoning_tokens` (when > 0). A count that
  is missing or not a non-negative integer drops its bucket; a bad `usage` never fails the attempt.
- `cost_details = {"total": usage.cost}` when OpenRouter reports a finite number (`0` on `:free`).
- A failed attempt is level `ERROR` with `status_message` = its status (`http_error: status=429`,
  `timeout`, `transport_error`, `bad_response`, `length`, `empty`, `no_json`). An attempt cut off by
  the job deadline is `ERROR` with `cancelled`.

### `recall-answer`

`metadata`: `task`, `hit` (`true`/`false`), `served_model` on a hit. `output`: the recorded answer.
A record that no longer validates counts as a miss, as in spec 05.

### Trace attributes

Set with `propagate_attributes` on entering `build-document-graph`, so every observation has them:

- `trace_name`: `build-document-graph`;
- `tags`: `["inkthread", "kind:sample"]` or `["inkthread", "kind:upload"]` (one Langfuse project
  holds every product);
- `metadata`: `job_id`, `document_id`;
- `session_id`: the request id the job runs under (`current_request_id()` inside the job's
  attribution, spec 13 § 2): the `X-Request-Id` bastion sent, so a dossier's traces across products
  group into one session. A job with no valid stored id has no session.

The root's `input` is `{kind, file_name}`; its `output` is `{status, graph_hash, nodes, edges}` on
success. Its metadata repeats `status`, `nodes` and `edges`, which are not document text, so an
upload's trace (no output, § 3) still says how the job ended. A failed job's root is `ERROR` with the
job's error code as `status_message`.

## 3. Uploads are metadata-only (DR-0029)

inkthread processes uploads without keeping them. A trace is kept by Langfuse for 30 days, so an
upload's trace holds **no document-derived text**: no prompt, no answer, no reasoning, no title,
label, quote or file name. It keeps the tree, the names and types, models, tokens, cost, latency,
levels and status messages. The two samples are public documents and keep full input and output.

One choke point enforces it: the client's `mask_otel_spans` hook, `withhold_upload_text`, which runs
on every span at export. It is fail-closed: unless a span carries the tag `kind:sample`, it deletes
the span's `input` and `output`, marks the span `withheld`, and deletes every metadata key outside a
fixed allowlist of ids, counts and codes. Status messages are codes by construction, and an
exception never leaves an observation with its message: the observation records the exception's
type as its `status_message` and the exception is re-raised outside it, so no span event or status
description can carry a document's words.

## 4. Failure behaviour

- Tracing never changes a job's outcome: with an exporter that fails, a job ends as it would without
  tracing.
- A stage or attempt that raises: its observation is `ERROR` (`status_message` = the exception type)
  and the exception propagates unchanged.

## 5. Test cases

Fast tier (an in-memory span exporter, no network):

- T-TR-1 Both keys → a client with them, `LANGFUSE_BASE_URL` and `APP_ENV` as environment, and
  `withhold_upload_text` as `mask_otel_spans`; either key unset or blank → `tracing_enabled=False`.
  `configure` installs the built client only with both keys; an unconfigured process gets one
  no-op client; `shutdown()` before first use does nothing.
- T-TR-2 `usage_details`: no counts → `{}`; prompt 10, completion 4 → `{input: 10, output: 4}`;
  cached 6 → `{input: 4, input_cached_tokens: 6, …}`; reasoning 3 → `{…, output: 1,
  output_reasoning_tokens: 3}`; zero details add no bucket; details larger than their total are
  capped at it; a detail without its total adds nothing. `cost_details`: `0` and `0.0012` → `{total}`;
  none → `None`.
- T-TR-3 `withhold_upload_text`: a span tagged `kind:sample` is left alone; one tagged `kind:upload`
  or with no tags loses `input` and `output`, gains `withheld`, keeps allowlisted metadata
  (`job_id`, `task`, `attempt`, …) and loses any other metadata key; trace name, tags, session,
  environment, model, usage and level stay.
- T-TR-4 A `step` whose body raises: `ERROR`, `status_message` = the exception type only, no
  `exception` span event, and the same exception re-raised; a cancelled body → `ERROR`
  `cancelled`, re-raised.
- T-TR-5 (respx) `429` then `200` on the primary → two `classify` generations: the first `ERROR`
  `http_error: status=429`, model the primary, attempt 1; the second `DEFAULT` with the messages in,
  the assistant message out, usage `{input: 9, input_cached_tokens: 3, output: 4,
  output_reasoning_tokens: 2}`, cost `{total: 0}`, `model_parameters` and metadata
  `{task, attempt: 2, provider}`.
- T-TR-6 A timeout, a transport error, `401`, `finish_reason: length`, empty content and a reply
  without JSON are each one `ERROR` generation with that status; the `no_json` reply's text is its
  output.
- T-TR-7 A reply with `reasoning` keeps it on the output; unreadable usage (strings, negatives,
  `NaN`, not an object) never fails the attempt and drops only its own bucket.
- T-TR-8 `run_task`: a recorded hit → one `recall-answer` (`hit: true`, the served model, the answer
  as output) and no generation; a live miss → `recall-answer` (`hit: false`) then the generation;
  a replay miss → `recall-answer` only; mode `off` → nothing.

Composed tier (Postgres, the in-process reader, the real `JobRunner` and `OpenRouterModel` over
respx):

- T-TR-9 An upload sent with `X-Request-Id: dossier-9` → one trace: root `build-document-graph`
  (`chain`) with the eight stages in order and their types; `recall-answer` and the generations under
  the agent stages; on every observation trace name `build-document-graph`, tags `inkthread` and
  `kind:upload`, `job_id` and `document_id` metadata, environment `test` and session `dossier-9`;
  the root's metadata says `status: succeeded` with its node and edge counts.
- T-TR-10 That upload's exported spans have no `input` or `output`, and no attribute, span event
  or status description holds the document's title, a word of its text or its file name.
- T-TR-11 A sample (sample mode `live`) is tagged `kind:sample` and keeps its input and output: the
  prompts hold the document's text, the root's input its file name.
- T-TR-12 An upload without `X-Request-Id` → no observation has a session.
- T-TR-13 A PDF the reader refuses → `read-pdf` and the root are `ERROR` with the job's error code.
- T-TR-14 An exporter that raises on every export → the job still succeeds.
- T-TR-15 The app's lifespan ends with one `tracing.shutdown()`.
