# 10 · Operations: configuration, health, deployment, CI

## 1. Configuration

`inkthread.core.config.Settings` (pydantic-settings) reads the environment, then `.env`. It is built
once at startup and validated there, so a bad configuration fails the boot, not the first request.

| variable | default | rule |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` or `production` |
| `LOG_LEVEL` | `INFO` | |
| `PORT` | `8000` | |
| `DATABASE_URL` | — | required; Neon URLs are normalised (spec 08 § 1) |
| `CORS_ORIGINS` | `http://localhost:3000` | comma-separated; `*` is refused in production |
| `ADMIN_TOKEN` | unset | admin routes answer `503 admin_disabled` while unset |
| `METRICS_TOKEN` | unset | `/metrics` answers `503` while unset, and otherwise wants `Authorization: Bearer` |
| `BLOB_STORE` | `local` | where samples keep their files: `local`, `postgres` or `r2` |
| `BLOB_ROOT` | `./var/blobs` | for `local` |
| `UPLOAD_ROOT` | `<tmp>/inkthread-uploads` | uploads' transient files (spec 08 § 2) |
| `UPLOAD_TTL_MINUTES` | `60` | how long an upload's results stay; 1 to 1440 |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_ENDPOINT` | — | required when `BLOB_STORE=r2` |
| `R2_PREFIX` | `inkthread/` | |
| `OPENROUTER_API_KEY` | — | required when `LLM_MODE=live` |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | |
| `OPENROUTER_MODEL_PRIMARY` | `nvidia/nemotron-3-super-120b-a12b:free` | producer |
| `OPENROUTER_MODEL_FAST` | `google/gemma-4-31b-it:free` | verifier; must differ from PRIMARY |
| `OPENROUTER_MODEL_FALLBACK` | `google/gemma-4-26b-a4b-it:free` | |
| `OPENROUTER_SITE_URL`, `OPENROUTER_APP_NAME` | the frontend URL, `inkthread` | sent as `HTTP-Referer`, `X-Title` |
| `LLM_MODE` | `live` | `live`, `replay` or `off` (spec 05 § 2) |
| `SAMPLE_LLM_MODE` | `replay` | samples run under the stricter of this and `LLM_MODE` (spec 11 § 3) |
| `LLM_MAX_REQUESTS_PER_DOCUMENT` | `8` | |
| `LLM_DAILY_REQUEST_CAP` | `40` | |
| `LLM_ACCOUNT_RESERVE` | `10` | |
| `LLM_MAX_TOKENS` | `12000` | |
| `LLM_TIMEOUT_S` | `90` | per attempt |
| `MAX_UPLOAD_BYTES` | `15728640` | |
| `MAX_PAGES` | `40` | |
| `MAX_QUEUE` | `10` | |
| `UPLOADS_PER_HOUR` | `5` | per client IP |
| `JOB_TIMEOUT_S` | `900` | |
| `READ_TIMEOUT_S` | `300` | |
| `READ_MEMORY_LIMIT_MB` | `0` | `0` disables the limit |
| `COMMIT_SHA` | — | else `RENDER_GIT_COMMIT`, else `GITHUB_SHA`, else `unknown` |

The model slugs were checked against OpenRouter's catalogue on 2026-10-14. They are configuration,
never validated against an allow-list (FeeLedger N-10).

## 2. Health, version, metrics

- `GET /health` returns `{status, version, commit_sha, db}`. It runs `SELECT 1` with a 5 s timeout and
  answers `503` when `db` is `down` (convention-ops-baseline).
- `GET /version` returns `{version, commit_sha, pipeline_version, inkgrid_version, graph_schema}`.
- `GET /metrics` serves Prometheus metrics through prometheus-fastapi-instrumentator, behind
  `METRICS_TOKEN`.
- Logs are structlog: JSON in production, console otherwise, with the request id bound on every line.
  Secrets are never logged.

## 3. Deployment

- **Image.** `python:3.12-slim`, `uv sync --frozen --no-dev`, a non-root user. The entrypoint runs
  `alembic upgrade head` when `DATABASE_URL` is set; Render's free plan ignores `preDeployCommand`.
  Then `uvicorn inkthread.main:app --proxy-headers --forwarded-allow-ips "*"`.
- **Render.** One free web service with `healthCheckPath: /health`. Secrets are `sync: false`. It
  points at the Neon branch `inkthread`; samples keep their files in Postgres (`BLOB_STORE=postgres`).
- **Smoke.** The repository variable `SMOKE_BASE_URL`, a bare origin, feeds a push-only CI job that
  probes `/health` and `/samples`. It skips itself when unset.

## 4. CI (`.github/workflows/ci.yml`)

| job | runs |
|---|---|
| lint | `ruff check`, `ruff format --check`, `mypy --strict src` |
| test | `pytest -m "not integration and not smoke"` with `--cov-branch --cov-fail-under=80` and per-module floors |
| integration | `pytest -m integration`: Postgres via Testcontainers, the real reader child process, and the composed upload → graph flow (spec 08 T-PJ-12, T-PJ-13) |
| build | `docker build` |
| smoke | push only, `vars.SMOKE_BASE_URL` |

## 5. Test cases

- T-OPS-1 Import graph:
  - `inkthread.domain` imports none of fastapi, sqlalchemy, httpx, langgraph, inkgrid or pymupdf;
  - `inkthread.services` imports no fastapi;
  - `inkthread.api` imports no `inkthread.models` or `inkthread.repositories`.
- T-OPS-2 Settings refuse `PRIMARY == FAST`, an unknown `LLM_MODE`, `CORS_ORIGINS=*` in production,
  `BLOB_STORE=r2` without its credentials, and `LLM_MODE=live` without a key.
- T-OPS-3 `/health` is 200 with `db: ok` against a live database and 503 with `db: down` when the
  database is unreachable.
- T-OPS-4 `/metrics` is 503 without a configured token, 401 without a bearer, and 200 with the right one.
- T-OPS-5 `/version` reports the pipeline version, inkgrid's version and the graph schema.
- T-OPS-6 The commit SHA falls back through `COMMIT_SHA`, `RENDER_GIT_COMMIT` and `GITHUB_SHA` to
  `unknown`.
- T-OPS-7 `[tool.uv] required-version` and the `uv_build` requirement admit uv 0.12.18 (the uv
  Dependabot's updater runs; a floor above it fails every update with `tool_version_not_supported`)
  and the uv the image copies.
