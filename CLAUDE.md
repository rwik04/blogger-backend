# CLAUDE.md

Guidance for Claude Code (and any other AI agent) working in this repository.
This is the source of truth for "how we build things here" — read it before
making structural changes, adding a new agent, or touching the DB layer.

## What this is

`blogger-backend` is a five-stage pipeline that turns a topic into a
published, SEO-optimized, fact-checked, UPSC-current-affairs blog post:

```
Topic Generator -> Researcher -> Strategist -> Writer -> Finisher
  (topic ideas)    (facts)      (SEO+outline) (draft)   (audit+quiz+media)
```

Each stage is a **standalone agent** — its own package, its own DB table(s),
its own CLI entrypoint, its own FastAPI router. There is **no orchestrator**
chaining stages together automatically. A human (or, eventually, a cron/queue)
calls one stage, waits for it to finish, then calls the next. This is a
deliberate, load-bearing decision — see "No auto-chaining" below before
"fixing" it.

## Core architectural decisions (read this before changing anything)

### 1. No LangChain / LangGraph — a custom graph engine instead

Every agent is built on `src/graph/engine.py`, ~160 lines, zero dependencies:
plain async functions over a shared mutable `state: dict`, wired together
with `Graph.add_node()` / `add_edge()` / `add_conditional_edge()` (which can
loop back "up" the graph — used for retries) / `add_fanout_node()` (bounded
concurrency, the replacement for LangGraph's `Send` API). `Graph.compile()`
returns a `CompiledGraph` you `await .arun(initial_state)`.

Why: this project intentionally ditched LangGraph/LangChain early on in favor
of the native OpenAI client + a hand-rolled graph, for full control over
context management (see "context compaction" below) and to avoid a heavy
abstraction layer for what is, per-agent, a fairly linear pipeline.

Don't reach for LangGraph/LangChain/any agent framework here. If a new agent
needs graph-like orchestration, build it as nodes on `graph.engine.Graph`,
matching the existing five agents.

### 2. Agent module shape (copy this exactly for any new agent)

```
src/agents/<agent_name>/
  models.py       Pydantic contracts: <Agent>Input, <Agent>Output, and any
                  internal StrictSchema classes used for LLM structured output
  nodes/
    <step>.py     One file per graph node. Each exports a make_<step>_node(...)
                  factory that closes over dependencies (LLMClient, MCPClient,
                  repo) and returns an async NodeFn: dict -> dict.
  pipeline.py     build_<agent>_graph(...) — wires nodes onto a Graph.
                  Named pipeline.py, NOT graph.py — a same-named sibling of
                  the top-level `graph` package breaks `from graph.engine
                  import ...` if this file is ever run as a script directly
                  (script execution prepends its own dir to sys.path).
  <agent_name>.py <Agent> class: owns dependencies (LLMClient, repo, ...),
                  exposes one async run(input) that drives one pass through
                  the compiled graph. Has a classmethod from_env() that reads
                  env vars and builds real dependencies — the constructor
                  itself takes plain args so tests can inject fakes.
  __main__.py     CLI entrypoint: uv run python -m agents.<agent_name> ...,
                  also exposed as a `uv run <script-name>` via pyproject.toml.
src/agents/prompts/<agent_name>.py
                  ALL prompt text lives here, not inline in nodes/. System
                  prompts as module-level string constants, user prompts as
                  build_<x>_user_prompt(...) functions. Keeps node files
                  focused on orchestration, prompt tuning a one-directory job.
```

No `__init__.py` files anywhere under `src/` — every package is an implicit
namespace package. Don't add them.

### 3. Context compaction (Researcher-specific, but the pattern generalizes)

LLM context windows are finite; raw scraped web pages are not. The
Researcher never feeds raw page text back into a subsequent LLM call —
`compact_round` immediately reduces every scrape into atomic,
source-attributed `Claim`s (with `source_ids`, `confidence`,
`contradicted`), and only the running claim list (not raw text) is what
gets carried forward round-to-round and handed to `write_report`. If you add
a stage that does iterative multi-round work, follow this shape: extract
structured facts immediately, discard raw text, accumulate only the
structured form.

### 4. LLM calls: always through `LLMClient`, always with a schema when possible

```python
from llm.client import LLMClient
client = LLMClient(provider="openai", api_key=..., model=...)

client.complete(messages, reasoning_effort="low")        # free-text
client.reason(messages, SomeStrictSchema, reasoning_effort="low")  # structured
```

- Never call the OpenAI SDK directly from a node. Always go through
  `LLMClient`/`BaseLLMAdapter` (`src/llm/`), so provider-swapping stays a
  one-function change (`create_adapter`).
- Every structured-output schema extends `agents.schema_base.StrictSchema`,
  which forces `additionalProperties: false` — required for OpenAI's
  structured-output mode to reject hallucinated extra fields.
- `reasoning_effort` is `"low" | "medium" | "high" | None`, threaded through
  every agent's constructor and overridable via a per-agent env var
  (`STRATEGIST_REASONING_EFFORT`, `WRITER_REASONING_EFFORT`,
  `FINISHER_REASONING_EFFORT`, `TOPIC_GENERATOR_REASONING_EFFORT`). Default
  to `"low"` for small/batched tasks (keyword extraction, classification,
  candidate extraction) and `"medium"`+ only for tasks that actually need
  deeper reasoning (drafting prose, fact-checking, quiz generation). Faster
  and cheaper beats "just in case" reasoning depth in this codebase.
- Never let the model assign IDs, order indices, or other bookkeeping
  fields that code can assign deterministically — see "Code-assigned IDs"
  below.

### 5. Code-assigned IDs, never LLM-assigned

Recurring pattern across every agent: whenever a list of things needs a
stable identifier or an ordering, the LLM's structured-output schema omits
that field, and the node assigns it in Python immediately after the call,
positionally zipped back onto the LLM's response:

- Researcher: claim `id`s assigned in `compact_round`, not by the model.
- Strategist: outline section `order_index`/`grounded` computed in code, not
  requested from the model.
- Writer: `word_count` computed in code (`drafting.py`), never trusted from
  the model's own claim.
- Finisher: quiz option lookup tables assembled deterministically in code.
- Topic Generator: `candidate_id` is a fresh `uuid4()` assigned in
  `extract_candidates`, never emitted by the model; `classify`'s response is
  zipped positionally onto the candidate list it was given, index-for-index.

If you add a node that maps an LLM response back onto a list of inputs,
default to positional zip + code-assigned bookkeeping fields, not trusting
the model to echo back an identifier faithfully.

### 6. MCP for web access — one thin client, no LangChain adapter

`src/mcpclient/client.py` wraps the official `mcp` Python SDK directly
around Exa's `exa-mcp-server` (spawned over stdio via `npx`). One
`MCPClient` (`async with get_exa_client() as mcp:`) is opened per agent run
and reused across every tool call in that run — not re-spawned per call.
Nodes call `mcp.call_tool("web_search_exa", {...})` /
`mcp.call_tool("crawling_exa", {...})` directly; there is no
LangChain-MCP-adapter layer. If a future agent needs different/additional
MCP tools or a different provider, extend `mcpclient/client.py`, don't
introduce a new abstraction.

Exa's `web_search_exa` sometimes returns `structuredContent`, sometimes
freeform text. Parsing always tries `structuredContent` first and falls
back to a plain-text `Field: value` parser (see
`agents/researcher/nodes/search.py` and
`agents/topic_generator/nodes/search_candidates.py` for two independent,
intentionally-not-shared implementations — the Researcher needs the fuller
`RawSearchHit`/scrape-decision shape, Topic Generator only needs
title/url/snippet).

### 7. Retry patterns — bounded, budgeted, never silent

Several agents retry sub-steps against explicit, small budgets rather than
looping indefinitely or failing hard on the first imperfection:

- **Strategist** (`draft_plan`): retries on outline business-rule failures.
- **Writer** (`write_section`, shared via `nodes/drafting.py`'s
  `draft_with_retries`): retries per-section on unsupported claim gaps and
  on insufficient length, independent budgets, plus a "consecutive
  failures" counter so one bad section doesn't hard-fail the whole run.
- **Finisher** (quiz): over-generates candidate questions, then
  validates/filters/selects in pure Python — budget is "generate N extra,
  drop what fails," not "retry the LLM call."
- **Topic Generator** (`dedup_filter`/`route_after_dedup`): if every
  candidate in a round comes back `similar_to_existing`, loops back to
  `extract_candidates` exactly **once** with a diversity nudge, then
  proceeds regardless of the outcome on the second attempt. Never silently
  returns an empty result, never loops more than once.

When adding a new retry loop: give it an explicit, small bound; never let a
`while True` depend solely on an LLM eventually producing a "good enough"
result.

### 8. No auto-chaining between stages (currently)

`Topic Generator -> Researcher -> Strategist -> Writer -> Finisher` are five
independent CLI/API calls, not one pipeline. `auto_approve` on Topic
Generator only *marks* a candidate `selected` — it does not itself call the
Researcher. `POST /topics/{id}/select` is the one place that explicitly
chains two stages (select -> kick off a Researcher run), and it does so as
an explicit, visible action, not a hidden side effect buried in a "finish
this stage" call. If/when a real orchestrator is built, it should sit
*above* these agents (a new caller invoking `Agent.run()` in sequence), not
be smuggled into any one agent's internals.

## Database layer

- SQLAlchemy **Core** (not ORM) throughout — `Table()` objects in
  `src/db/tables.py`, raw `select()`/`insert()`/`update()` in repositories.
  No models/ORM mapping layer.
- `src/db/engine.py`: `get_engine()` is a process-wide, `lru_cache`d, pooled
  engine built from `DatabaseSettings.from_env()` (`src/db/settings.py`,
  reads `DB_*` env vars). `warm_pool(engine)` eagerly opens/returns pool
  connections — called once at API startup (`api/main.py`'s `lifespan`) so
  the first real request doesn't pay cold-connection latency.
- **Migrations**: `src/db/migrations/NNNN_description.sql`, plain SQL,
  applied in filename order by `src/db/migrate.py` (`uv run python -m
  db.migrate`), tracked in a `schema_migrations` table so each file runs
  exactly once. No Alembic, no ORM-driven autogeneration. When you need a
  schema change: write a new numbered `.sql` file (never edit an already-
  applied one), mirror the resulting shape in `src/db/tables.py`.
- **Repositories**: one per agent (`ResearchRepository`,
  `StrategistRepository`, `WriterRepository`, `FinisherRepository`), each
  extending `BaseAgentRepository` (`src/db/repositories/base.py`) for the
  shared `blog_runs`/`agent_events` operations (`get_run`, `set_run_status`,
  `emit_event`, `list_events`). Agent-specific `save_*`/`load_*` methods
  live on the subclass. `NotFoundError` exceptions are centralized in
  `src/db/repositories/errors.py` (`AgentOutputNotFoundError` and its
  subclasses, `SectionNotFoundError`, `TopicBatchNotFoundError`,
  `TopicNotFoundError`) so the API layer's exception handlers stay generic.
  `ResourcesRepository` is the odd one out: read-only aggregate queries
  (counts, listings) for the `/stats` dashboard endpoint, not tied to any
  one agent.
- **Topic Generator is the one exception** to the `blog_runs`/`agent_events`
  pattern: it runs *before* any `blog_runs` row exists, so it owns a
  parallel pair of tables (`topic_batches`/`topic_batch_events`) instead,
  via its own `TopicRepository` (deliberately not a `BaseAgentRepository`
  subclass). `blog_runs.topic_id` (nullable FK to `topics.id`) is the only
  link back — set when a run starts from a selected topic candidate, left
  null for ad-hoc raw-string topics.
- **Dedup by trigram similarity**: Topic Generator uses Postgres's
  `pg_trgm` extension (`similarity()` SQL function, `gin_trgm_ops` index on
  `topics.title`) for fuzzy-duplicate detection against topic history — no
  embeddings, no vector DB, no new Python dependency. Bands: `>=0.4` auto
  "similar," `0.25–0.4` ambiguous (one LLM tiebreak call), `<0.25` "new."

## API layer (`src/api/`)

- FastAPI. One router per stage (`api/routers/{runs,research,strategist,
  writer,finisher,resources,topics}.py`), included on `app` in `main.py`.
- **Execution model**: every mutating (`POST`) endpoint does a fast
  synchronous prerequisite check (via repository `load_*`, which raises the
  relevant `*NotFoundError`/`AgentOutputNotFoundError` if a prior stage
  hasn't completed), schedules the actual agent call as a `BackgroundTask`
  (via `api/jobs.py`'s `run_and_log`, which logs but doesn't re-raise —
  background tasks have no caller to propagate exceptions to), and returns
  `202 {id, status: "queued"}` immediately. Clients poll `GET
  /runs/{run_id}` + `GET /runs/{run_id}/events` (or the `topic_batches`
  equivalents) for progress — no separate job-tracking table, this reuses
  `blog_runs.status`/`agent_events` (or `topic_batches`/
  `topic_batch_events`) that the CLI already writes to.
- **Error mapping** (registered once in `main.py` via
  `@app.exception_handler(...)`, not per-route try/except):
  `RunNotFoundError`/`SectionNotFoundError`/`TopicBatchNotFoundError`/
  `TopicNotFoundError` -> 404 (doesn't exist at all);
  `AgentOutputNotFoundError` -> 409 (the run exists, but a prerequisite
  stage hasn't produced output yet — a state conflict, not a missing
  resource).
- **Dependency injection** (`api/deps.py`): the four/five agents are built
  once in `main.py`'s `lifespan` (`app.state.<agent> = <Agent>.from_env()`)
  and shared across requests (cheap, stateless); repositories are built
  fresh per-request (`get_engine()` itself is cached, so this is cheap too).
  Tests override individual `Depends()` getters via
  `app.dependency_overrides[deps.get_x] = lambda: stub`, never hit a real
  DB/LLM/MCP.
- **Testing FastAPI routes**: build `TestClient(app)` *without* the `with`
  statement (`c = TestClient(app); yield c` in a fixture) — using it as a
  context manager triggers `lifespan`, which calls every agent's
  `from_env()`, which needs real env vars (`OPENAI_API_KEY`, etc.) that
  `pytest` doesn't load automatically. Skipping `with` skips `lifespan`
  entirely; all dependencies under test come from `dependency_overrides`.
- **API-only schemas** live in `api/schemas.py`, separate from each agent's
  own Pydantic contracts (`ResearcherInput`, `WriterOutput`, ...) — the
  agent contracts stay the source of truth for what gets persisted/passed
  between stages; the API schemas exist purely to shape the HTTP surface
  (e.g. accepting a raw string `topic_id`/`run_id` instead of a full nested
  object).

## Running things

```bash
uv sync --extra dev        # installs pytest etc; plain `uv sync` won't
cp .env.example .env       # fill in OPENAI_API_KEY, EXA_API_KEY, DB_*
uv run python -m db.migrate

uv run research "<topic>" [--audience-tag UPSC] [--run-id <id>]
uv run strategize --run-id <id> [--audience-tag UPSC]
uv run write --run-id <id>
uv run finish --run-id <id> [--quiz | --no-quiz]
uv run generate-topics --mode autonomous|directed [--instruction "..."] [--count N] [--auto-approve]

uv run serve-api            # FastAPI on :8000 (override via API_HOST/API_PORT)
uv run pytest -q
```

No orchestrator wires these together — each is a separate, sequential
invocation against the DB row(s) the previous stage left behind (except
`POST /topics/{id}/select`, see above).

## Testing conventions

- Every node function is tested in isolation with hand-built stub
  `LLMClient`/`TopicRepository`/etc. objects (`def reason(self, messages,
  schema, reasoning_effort=None): ...`) — no mocking framework, no real
  OpenAI/DB/MCP calls in unit tests.
- Pipeline-level routing (retry loops, conditional edges) gets its own test
  file per agent (e.g. `test_finisher_pipeline_routing.py`,
  `test_topic_generator_pipeline_routing.py`), running the real compiled
  graph (or a slice of it) end-to-end against stubs, asserting on call
  counts and final state — not just on individual node outputs.
- API routes are tested via `TestClient` + `dependency_overrides`, one file
  per router group, asserting response codes/shapes, not integration-testing
  the real agents.
- `uv run pytest -q` should stay fast (no network, no real DB) — anything
  that needs real Exa/OpenAI/Postgres is a manual verification step, not
  part of the automated suite.
