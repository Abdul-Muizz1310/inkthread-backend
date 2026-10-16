# 🧵 `inkthread-backend`

> 🕸️ **A born-digital PDF, as a knowledge graph of its own parts and the threads between them.**
> Every node is the page's own words; every thread carries the span that licenses it.

🔗 [Frontend](https://github.com/Abdul-Muizz1310/inkthread-frontend) · 📖 [Why](WHY.md) · 🏗️ [Architecture](docs/ARCHITECTURE.md) · 📐 [Design specs](docs/specs/00-design.md) · 🧾 [Graph contract](docs/specs/01-graph-contract.md)

![python](https://img.shields.io/badge/python-3.12-3776ab?style=flat-square&logo=python&logoColor=white)
![ci](https://img.shields.io/github/actions/workflow/status/Abdul-Muizz1310/inkthread-backend/ci.yml?style=flat-square)
![mypy](https://img.shields.io/badge/mypy-strict-blue?style=flat-square)
![langgraph](https://img.shields.io/badge/LangGraph-pipeline-1c3c3c?style=flat-square)
![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)

---

```console
$ curl -F file=@fee-schedule.pdf $API/documents
{"document": {"id": "…", "status": "queued"}, "job": {"id": "…"}}

$ curl -N $API/jobs/<job>/events
event: stage   data: {"stage": "read", "status": "completed", "ms": 27400}
event: delta   data: {"stage": "structure", "nodes": [...], "edges": [...]}
event: llm     data: {"task": "A-classify", "model": "nvidia/nemotron-3-super-120b-a12b:free", "ok": true}
event: done    data: {"graph_hash": "…", "stats": {"nodes": 46, "edges": 59}}

$ curl $API/documents/<doc>/graph.cypher > graph.cypher   # straight into Neo4j
```

---

## 💡 Why this exists

"Chunk the PDF and ask a model for triples" gives a graph whose nodes are model-written summaries
and whose provenance stops at a 1,200-token chunk. For documents where structure is the meaning
(contracts, policies, fee schedules, standards) that loses what matters. It drops which footnote a call
points to, which definition a term uses, and which clause a "notwithstanding" displaces.

inkthread is Part 2 of the FeeLedger split. Part 1 is [inkgrid](https://github.com/Abdul-Muizz1310/inkgrid),
the text-layer reader. Rules build most of the graph from inkgrid's reading. Free models only type and
relate what the rules left open, and a second model judges those claims. Models emit structure, never
text: a quote they give counts only when it snaps to the page's own words.

---

## ✨ Features

- 📄 **Structure first** — sections from printed numbers and type size, tables down to the cell with header paths, footnote calls, continuations
- 🧭 **18 roles** — obligation, permission, prohibition, condition, exception, definition, computation… each with the cue that fired as evidence
- 🧵 **11 thread types** — contains, continues, cites_note, defines, uses_term, refers_to, cites_external, governs, qualifies, overrides, illustrates
- 🤖 **Agents on the residual** — LangGraph stages `classify_agent`, `relate_agent`, `verify_agent` over OpenRouter `:free` models, about eight calls a document
- 🔒 **Grounding** — every model quote must snap to the page; ungrounded claims are dropped and listed, never shipped
- 🧾 **Explain gate** — a hash-chained op log must account for every node, role and thread before a graph is stored
- 🔁 **Byte-identical replay** — recorded model answers by request key; the same PDF gives the same `graph_hash` with zero calls
- 📡 **Live build** — SSE `stage` / `delta` / `llm` events, resumable with `Last-Event-ID`; the event log replays the build any time later
- 📤 **Exports** — JSON, JSON-LD (DoCO, SKOS, PROV-O, Web Annotation), GraphML, Cypher

---

## 🏗️ Architecture

```mermaid
flowchart LR
  U[PDF] --> API[FastAPI] --> Q[(jobs, events<br/>Postgres)]
  Q --> R[JobRunner]
  R --> G
  subgraph G[LangGraph pipeline]
    direction LR
    read[read<br/>inkgrid in a child process] --> st[structure] --> cr[classify rules] --> ca[classify agent] --> lr[link rules] --> ra[relate agent] --> va[verify agent] --> fin[finalize]
  end
  ca & ra & va -.-> OR[OpenRouter :free]
  fin --> GR[(graph JSON + op log)]
  G --> SSE[SSE events] --> FE[Next.js viewer]
```

The domain is a pure core with no I/O. A test on the import graph enforces the layering: routers →
services → repositories → models, and services never import FastAPI.

---

## 📁 Project structure

```
src/inkthread/
├── domain/        pure core: contract, draft, ids, ops, structure/, classify/, link/,
│                  confidence, explain, finalize, why, exports/
├── reader/        inkgrid adapter, spawned child process, PDF inspection
├── llm/           OpenRouter client, cascade, budget, request keys
├── agents/        grounding, prompts/*.md, classify, relate, verify
├── pipeline/      the LangGraph state graph
├── services/      ingest, job runner, broadcast, streams, sweep, samples
├── repositories/  SQL; models/ ORM; schemas/ DTOs; api/ routers + SSE
└── core/, platform/, storage/   config, errors, logging, health, blobs
docs/specs/        00-design … 10-ops, each with its enumerated test cases
samples/           public-domain PDFs + recorded model answers
```

---

## 💻 Usage

```bash
uv sync
docker run -d -e POSTGRES_PASSWORD=dev -p 55432:5432 postgres:17-alpine
export DATABASE_URL=postgresql://postgres:dev@localhost:55432/postgres LLM_MODE=replay
uv run alembic upgrade head
uv run inkthread seed                # samples, replayed from samples/answers with zero calls
uv run uvicorn inkthread.main:app    # http://localhost:8000/docs
```

| Route | Does |
|---|---|
| `POST /documents` | upload a PDF (15 MB, 40 pages); `202 {document, job}` |
| `GET /jobs/{id}/events` | the live build as SSE |
| `GET /documents/{id}/graph` (`.jsonld`, `.graphml`, `.cypher`) | the graph and its exports |
| `GET /documents/{id}/pages/{n}.png`, `/pages/{n}/geometry` | page images and word geometry |
| `GET /documents/{id}/why/{element}` | the rule or model behind any node, role or thread |
| `GET /samples`, `/health`, `/version`, `/metrics` | samples and operations |

Configuration is in [`.env.example`](.env.example) and [spec 10](docs/specs/10-ops.md).

---

## 🧱 Stack

| Concern | Choice |
|---|---|
| PDF reading | inkgrid 0.1 (PyMuPDF, Camelot, PDFium verifier), in a spawned child process |
| Pipeline | LangGraph 1.2, no checkpointer (the job row and event log are durable) |
| LLM | OpenRouter `:free` cascade, strict JSON schema, recorded answers |
| API | FastAPI 0.143, sse-starlette, Pydantic v2 |
| Data | SQLAlchemy 2.1 async + asyncpg, Alembic, Neon Postgres |
| Files | samples in Postgres (or disk, or R2); uploads on the instance's temporary disk for an hour |
| Quality | Ruff, mypy `--strict`, pytest, Hypothesis, respx, Testcontainers |

---

## 🧪 Testing

| Metric | Value |
|---|---|
| Tests | 450+ (unit, property and integration) |
| Integration | real Postgres (Testcontainers), the real reader child process, the composed upload → graph flow |
| Property tests | Hypothesis: spans, ids, section-tree invariants, partition, grounding |

```bash
uv run pytest -m "not integration"   # unit
uv run pytest -m integration         # needs Docker
```

---

## 🏛️ Engineering philosophy

| Principle | Here |
|---|---|
| Spec-TDD | eleven specs, every test traces to a spec case id |
| Negative space | the graph model rejects an invalid graph at construction |
| Pure core | `domain/` does no I/O; the shells are reader, llm, agents, pipeline, services |
| Honest numbers | no precision figure is claimed until a hand-labelled edge set exists |

---

## ⚠️ Scope and limitations

- Born-digital PDFs only; inkgrid does no OCR, so a scanned PDF fails with `no_text_layer`.
- Free models are slow, flaky and budget-bound (50 requests a day per account); past the quota a graph
  is rules-only, with the skipped stages named.
- Rules can over-link capitalised common words defined as terms.
- Uploads are processed, not kept: the PDF is deleted when its job ends, and the graph and page images
  an hour later (or at the next restart). Text does go to OpenRouter's free providers, which may log it.

---

## 📍 Status

v0.1, 2026-10-14. Samples: the USPTO fee schedule and the NIST AI Risk Management Framework.

---

## 📜 License

MIT — see [LICENSE](LICENSE). inkthread depends on PyMuPDF (AGPL-3.0); software served over a network
with it must meet the AGPL's terms for the combined work, which is why this source is public.

---

> 🧵 *Every thread grounded in the page's own words.*
