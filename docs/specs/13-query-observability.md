# 13 · Query observability (slowquery-detective 0.2)

bastion's dossier measures what each service did for it: it sends `X-Request-Id: R` with its calls,
then asks `GET /_slowquery/queries?request_id=R`. inkthread installs slowquery-detective 0.2 to answer.

## 1. Wiring

- `create_app` builds the database engine at construction (it opens no connection) so that
  `install(app, engine, service="inkthread", store_url=DATABASE_URL, authorize=bastion_only)` can run
  there, after the app's own middleware (platform token, request ids, CORS). The lifespan uses that
  engine and still disposes of it on shutdown. Nothing else about startup or shutdown changes.
- The store is the service's own Postgres: schema `slowquery`, created by the library on boot
  (`CREATE … IF NOT EXISTS` under an advisory lock), outside Alembic.
- `authorize` (`bastion_only`) answers `True` only for a request the platform-token middleware
  authenticated with bastion's key (`iss: "bastion"`). The middleware runs first, so:
  - no token → `401 missing_platform_token` (or, under `DEMO_MODE` or the test settings, the request
    reaches the hook anonymous and gets `403`);
  - a frontend-key token → `403`;
  - a bastion token → the routes answer.

## 2. Jobs keep the upload's request id

A document is processed by the job runner, a background task started in the lifespan, so its queries
run outside any request's context and would be attributed to nobody. A dossier upload's receipt would
then miss the work it caused. So the request id travels with the job:

1. `POST /documents` (and the admin's reprocess) reads the request's tagged id (the library's
   `current_request_id()`, the `X-Request-Id` it accepted) and stores it on the new job
   (`jobs.request_id`, migration `0004`, `ADD COLUMN IF NOT EXISTS`).
2. The runner runs the claimed job under that id (`inkthread.core.request_scope.attributed_to`), so
   every statement of the pipeline and of storing its results counts against R.
3. A deduplicated upload creates no job and attributes nothing new; a job with no id (an upload
   without the header, a seed) is attributed to nobody, as before.

`attributed_to` sets the library's request-id context variable, which 0.2 does not expose as API; a
test pins it to `current_request_id()`, so a library change that breaks it fails CI.

## 3. Test cases

- T-SQ-1 `GET /documents/{id}/graph` with `X-Request-Id: R` is listed by
  `GET /_slowquery/queries?request_id=R` with a bastion token (real Postgres).
- T-SQ-2 `/_slowquery/queries` with no token → 401; with a frontend token → 403; anonymous under the
  test settings → 403.
- T-SQ-3 An upload with `X-Request-Id: U` stores U on its job, and the job's own statements (its
  events, its graph) are listed under U.
- T-SQ-4 `attributed_to(R)` makes `current_request_id()` R inside and restores the outer value after;
  a malformed id attributes to nobody.
- T-SQ-5 The engine exists on `app.state` right after `create_app`, the lifespan uses that engine, and
  two lifespans in a row on fresh apps both serve `/health`.
- T-SQ-6 Migration `0004` adds `jobs.request_id`; a second `upgrade head` is a no-op; `downgrade 0003`
  drops it.
