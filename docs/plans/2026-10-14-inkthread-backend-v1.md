# inkthread backend v1: implementation plan

> **For agentic workers:** use subagent-driven development or executing-plans to work through this plan
> task by task. Steps use checkboxes. Every task is Spec-TDD: write the spec's enumerated tests first
> (they are listed by id in each spec's last section), watch them fail, then implement.

**Goal:** a FastAPI service that turns a born-digital PDF into the `inkthread.graph/1` knowledge graph
through a LangGraph pipeline (inkgrid → rules → agents → verify → finalize), streams the build over
SSE, and stores everything in Postgres and a blob store.

**Architecture:**
- A pure `domain` core: contract, draft, ids, structure, classify, link, confidence, explain, exports.
- Imperative shells around it: `reader` (child process), `llm` and `agents` (OpenRouter), `pipeline`
  (LangGraph), `repositories`/`services`/`api` (FastAPI, SQLAlchemy).
- Rules first, models on the residual (spec 00 D-1).

**Tech stack:** Python 3.12, uv, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 async + asyncpg,
Alembic, LangGraph, httpx, sse-starlette, structlog, prometheus-fastapi-instrumentator,
python-multipart, inkgrid 0.1.x (PyMuPDF, Camelot, pypdfium2), boto3. Tests: pytest, pytest-asyncio,
pytest-cov, hypothesis, respx, testcontainers[postgres], networkx and pyld (export checks).

**Spec:** `docs/specs/00-design.md` … `10-ops.md`. Read 00 and 01 before any task.

## Global constraints

- Python `>=3.12`; ruff line length 100, `select E,F,I,B,UP,N,SIM,RUF`; `mypy --strict` on `src/`.
- Layering (spec 00 § 3, enforced by T-OPS-1): `domain` imports nothing from fastapi, sqlalchemy,
  httpx, langgraph, inkgrid or pymupdf.
- Graph schema string `inkthread.graph/1`; `PIPELINE_VERSION = "1.0.0"` in `inkthread/__init__.py`.
- Text reaches a node only from the Reading. No code path writes model text into the graph.
- Every enum is closed (spec 01 § 4). Every rule id named in the specs appears in `domain/catalog.py`.
- Commits: Conventional Commits, imperative, at most 72 characters, no emoji, **no Co-Authored-By
  trailer**.
- Coverage: `--cov-branch --cov-fail-under=80` overall, and at least 85% on `inkthread/domain`.
- Tests touching the database use real Postgres via Testcontainers (`-m integration`). Never SQLite.

## Review focus

Five inputs no spec test exercises directly. Each one gets a test in the task named.

1. **A PDF with no headings at all.** Expect every part under the document, title null, a valid
   graph. → Task 4: `test_no_headings_document`.
2. **A 1-page PDF with only a table.** Expect one table node, quantitative role, `header_not_found`
   if inkgrid finds no header. → Task 5: `test_table_only_document`.
3. **Unicode text (accents, CJK, RTL marks) in quotes and ids.** Expect stable ids, valid spans and a
   working `snap`. → Task 2: `test_ids_unicode`; Task 13: `test_snap_unicode`.
4. **The same PDF uploaded twice while the first job is still running.** Expect one job, both
   responses pointing at it. → Task 18: `test_duplicate_upload_while_running`.
5. **A model answer whose JSON is valid but names every offered id with an empty quote.** Expect every
   claim rejected `no_evidence` or `quote_not_found` and a still-valid graph. → Task 13:
   `test_all_empty_quotes_rejected`.

---

### Task 1: Scaffold, configuration, import-graph guard

**Files:** `pyproject.toml`, `.python-version`, `.gitignore`, `.editorconfig`, `.env.example`, `LICENSE`
(MIT, Abdul-Muizz Anwar, 2026), `Makefile`, `src/inkthread/__init__.py`, `src/inkthread/core/config.py`,
every package's `__init__.py` from spec 00 § 3, `tests/conftest.py`, `tests/unit/test_config.py`,
`tests/unit/test_import_graph.py`.

**Produces:** `Settings` (pydantic-settings) with every variable in spec 10 § 1;
`get_settings() -> Settings` (lru-cached); `inkthread.__version__`, `PIPELINE_VERSION`.

- [ ] Write T-OPS-2 (settings refusals) and T-OPS-1 (import graph via `ast` over `src/`).
- [ ] Run them and see them fail. Implement `Settings` and the package skeleton. Run them and see them pass.
- [ ] `uv run ruff check`, `uv run ruff format --check` and `uv run mypy src` are clean.
- [ ] Commit `chore: scaffold inkthread backend`.

### Task 2: The contract, ids, draft and op log

**Files:** `domain/model.py`, `domain/ids.py`, `domain/text.py`, `domain/draft.py`, `domain/ops.py`,
`domain/catalog.py`, `cli.py` (`export-schema`), `docs/schema/graph.schema.json`.
Tests: `tests/unit/domain/test_model.py`, `test_ids.py`, `test_ops.py`.

**Produces:**
- `model.py`: every type in spec 01. `Graph` serialises with `by_alias=True` (`schema` key) and runs
  the § 7 invariants in a `model_validator`.
- `ids.py`: `fold(s) -> str`, `h(parts: Sequence[str]) -> str`, `document_id(sha)`,
  `section_id(ancestor_titles, text)`, `part_id(kind, section_titles, text)`, `term_id(key)`,
  `external_id(key)`, `edge_id(type, source, target, method, label)`,
  `TwinRegistry.claim(base_id) -> str` (adds `:2`, `:3` …).
- `text.py`: `cut_label(text, limit=80) -> tuple[str, bool]`,
  `sentences(text) -> list[tuple[int, int]]` (spec 04 § 1), `word_boundary_finditer(pattern, text)`.
- `draft.py`: `NodeDraft`, `RoleDraft`, `EdgeDraft`, `GraphDraft` with `add_node`, `add_edge`
  (returns False on a duplicate id), `add_role` (False when the role is present), `add_flag`,
  `add_unresolved`, `set_aside_block`, `set_verdict`, `reject`, `take_delta() -> Delta`. Each mutation
  appends an `Op` (spec 06 § 3).
- `ops.py`: `Op`, `genesis(sha, version)`, `chain(ops) -> (head, count)`, `verify(ops, head, count,
  sha, version) -> bool`.
- `catalog.py`: `RULES: Mapping[str, str]` (rule id → one-line statement) and
  `TASKS: Mapping[str, str]`.

- [ ] Write T-GC-1…18, plus `test_ids_unicode`, T-CP-4…6, and a draft test (duplicate edge
  collapses; every mutation adds exactly one op).
- [ ] Run them and see them fail. Implement. Run them and see them pass.
- [ ] Generate `docs/schema/graph.schema.json` with `python -m inkthread.cli export-schema` (T-GC-2
  pins it).
- [ ] Commit `feat(domain): add the graph contract, ids, draft and op log`.

### Task 3: Reading model, adapter and synthetic PDFs

**Files:** `domain/reading.py`, `reader/adapt.py`, `tests/support/pdfs.py` (PyMuPDF factory: headings,
paragraphs, a ruled table, footnote calls, hidden text, two pages, encrypted, image-only),
`tests/support/readings.py` (literal `Reading` builders), `tests/integration/reader/test_adapt.py`.

**Produces:** `Reading` and friends (spec 02 § 1); `adapt(document: inkgrid.Document, report:
inkgrid.VerificationReport | None) -> Reading`; `align_words(block, words) -> list[RWord]`.

- [ ] Write T-ST-1…4 on factory PDFs read by real inkgrid (in-process is fine in tests).
- [ ] Implement. See them pass. Commit `feat(reader): adapt inkgrid's reading`.

### Task 4: Structure I: set-aside, title, merge, section tree

**Files:** `domain/structure/setaside.py`, `title.py`, `sections.py`; tests under
`tests/unit/domain/structure/`.

**Consumes:** `Reading` (Task 3); `GraphDraft`, ids (Task 2).
**Produces:** `set_aside(reading) -> list[SetAside]`; `find_title(blocks) -> TitleResult`;
`merge_headings(blocks) -> list[HeadingGroup]`; `build_sections(blocks, title) -> SectionTree`
(parent of every block, depth, the section index keyed `(counter, number)` for spec 04 § 5).

- [ ] Write T-ST-5…21 and `test_no_headings_document`. See them fail, implement, see them pass. Commit.

### Task 5: Structure II: parts, tables, inkgrid edges, flags, geometry

**Files:** `domain/structure/parts.py`, `tables.py`, `inklinks.py`, `geometry.py`, `build.py`.

**Produces:** `build_structure(reading, draft) -> StructureResult` (fills the draft with the document,
sections, parts, `contains`, `continues`, `cites_note`, flags, set-aside, findings; returns the section
index and the per-page geometry); `cell_labels(grid) -> list[CellInfo]`.

- [ ] Write T-ST-22…32 and `test_table_only_document`. See them fail, implement, see them pass. Commit.

### Task 6: Classify rules and the residual

**Files:** `domain/classify/rules.py`, `residual.py`.

**Consumes:** `find_definitions` (Task 7) and `find_citations` (Task 8) through their module paths.
Write those two functions first if this task runs before them.

**Produces:** `classify(draft) -> None` (adds rule roles); `residual(draft) -> list[str]` (node ids).

- [ ] Write T-CL-1…24. See them fail, implement, see them pass. Commit.

### Task 7: Link I: definitions and terms

**Files:** `domain/link/definitions.py`, `terms.py`.
**Produces:** `find_definitions(text, *, block_term=None) -> list[DefinitionHit]`;
`link_terms(draft) -> None`.
- [ ] T-LK-1…8. Commit.

### Task 8: Link II: citations, references, identifiers

**Files:** `domain/link/citations.py`, `references.py`, `identifiers.py`.
**Produces:** `find_citations(text) -> list[CitationHit]`; `link_citations(draft)`;
`link_references(draft, section_index)`; `link_identifiers(draft)`.
- [ ] T-LK-9…20. Commit.

### Task 9: Link III: precedence, lead-ins, composition

**Files:** `domain/link/precedence.py`, `leadins.py`, `build.py` (`link_rules(draft, section_index)`
in spec 04's order).
- [ ] T-LK-21…26. Commit.

### Task 10: Confidence, explain, finalize, why

**Files:** `domain/confidence.py`, `explain.py`, `finalize.py`, `why.py`, `sketches.py`.
**Produces:** `score_node`, `score_role`, `score_edge` → `Confidence`; `explain(graph, reading, ops)
-> list[Violation]`; `finalize(draft, reading, *, config) -> FinalGraph(graph, ops)`;
`why(graph, ops, element_id) -> Why`; `sketch(delta) -> SketchBatch`.
- [ ] T-CP-1…3, 7…11. Commit.

### Task 11: Exports

**Files:** `domain/exports/jsonld.py`, `graphml.py`, `cypher.py`.
**Produces:** `to_jsonld(graph) -> bytes`, `to_graphml(graph) -> bytes`, `to_cypher(graph) -> bytes`.
- [ ] T-EX-1…7. Commit.

### Task 12: The LLM layer

**Files:** `llm/ports.py`, `keys.py`, `catalog.py`, `client.py`, `budget.py`.
**Produces:**
- `cjson(obj) -> str`; `request_key(task, version, schema, prompt_bytes, cascade, temperature,
  input) -> str`.
- `OpenRouterModel(settings, http: httpx.AsyncClient, catalog)` implementing `ModelPort`.
- `ModelCatalog.capabilities(slug) -> Capabilities`.
- `Budget(per_doc, daily_cap, reserve, counter, account_check)` implementing `BudgetPort`.
- [ ] T-AG-11…22b, T-AG-25 (respx for HTTP). Commit.

### Task 13: Agents

**Files:** `agents/grounding.py`, `prompts.py`, `prompts/classify.md`, `prompts/relate.md`,
`prompts/verify.md`, `runner.py`, `classify.py`, `relate.py`, `verify.py`.
**Produces:** `snap(text, quote) -> Span | None`; `run_task(...) -> TaskOutcome` (key → store → budget
→ model → schema); `classify_agent(draft, residual, deps) -> AgentReport`; `relate_agent(draft,
deps)`; `verify_agent(draft, deps)`.
- [ ] T-AG-1…10, 23, 24, `test_snap_unicode` and `test_all_empty_quotes_rejected`. Commit.

### Task 14: The pipeline

**Files:** `pipeline/state.py`, `deps.py`, `events.py`, `nodes.py`, `graph.py`.
**Produces:** `build_pipeline() -> CompiledStateGraph`. `run_pipeline(pdf_bytes, deps) ->
AsyncIterator[PipelineEvent]` yields `stage`/`delta`/`llm` events and finally a `PipelineResult`
(graph, ops, geometry, pngs, run stats).
- [ ] Composed tests on factory PDFs with an in-process reader and a scripted model:
  - the stages run in order;
  - agent stages skip with `budget` or `disabled`;
  - the final graph passes `explain`;
  - replaying recorded answers gives the same `graph_hash` with zero calls (G7).
- [ ] Commit.

### Task 15: The reader child process

**Files:** `reader/child.py`, `reader/process.py`, `reader/inspect.py`.
- [ ] T-PJ-8…11. Commit.

### Task 16: Persistence and blobs

**Files:** `core/db.py`, `models/*`, `alembic/env.py`, `alembic/versions/0001_initial.py`,
`repositories/*`, `storage/blobs.py`, `tests/integration/conftest.py` (Testcontainers Postgres,
Alembic via subprocess).
- [ ] T-PJ-1…7, T-PJ-14. Commit.

### Task 17: Services, runner, broadcast, retention

**Files:** `services/ingest.py`, `runner.py`, `broadcast.py`, `documents.py`, `retention.py`.
- [ ] Integration tests:
  - ingest dedupe and requeue;
  - the runner persists events in order and then broadcasts;
  - success writes the graph and blobs;
  - failure records its code;
  - the reaper requeues and fails.
- [ ] Commit.

### Task 18: The API

**Files:** `main.py` (`create_app`), `core/errors.py`, `core/logging.py`, `core/ratelimit.py`,
`platform/*`, `api/deps.py`, `api/sse.py`, `api/routers/*`, `schemas/*`.
- [ ] T-API-1…21, T-OPS-3…6, T-PJ-12, T-PJ-13, `test_duplicate_upload_while_running`. Commit.

### Task 19: Samples

**Files:** `samples/manifest.toml`, `samples/*.pdf`, `samples/README.md`, `samples/answers/`,
`services/samples.py`, `cli.py seed`.
- [ ] Seed both samples live once within the day's budget, then export the answers.
- [ ] A test seeds from the committed answers with `LLM_MODE=replay` and zero calls.
- [ ] Commit.

### Task 20: Ship

**Files:** `Dockerfile`, `docker-entrypoint.sh`, `render.yaml`, `.github/workflows/ci.yml`,
`.github/dependabot.yml`, `.github/pull_request_template.md`, `README.md` (house style, DR-0027),
`WHY.md`, `docs/ARCHITECTURE.md`, `docs/DEMO.md`.
- [ ] `docker build` runs, and the container answers `/health`.
- [ ] CI is green on GitHub.
- [ ] Deploy to Render with the Neon branch `inkthread` and the R2 prefix `inkthread/`.
- [ ] Set `SMOKE_BASE_URL`.
- [ ] Commit.
