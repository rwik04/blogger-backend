# Researcher agent — technical design

Scope: the first stage of the blog pipeline (`Researcher → Strategist → Writer → Fact-checker → Humanizer → Finisher → Supervisor`). Takes a raw topic, returns a structured, citation-backed research brief. Everything downstream — the outline, the draft, the fact-check pass — depends on this brief being accurate and traceable, so the design optimizes for **every claim being attributable to a source URL**, not for the fanciest retrieval.

## 1. Why MCP here, specifically

The Researcher's only external dependency is "search the web and read pages." Wrapping that as a hand-rolled `fetch()` + HTML parser is brittle (rate limits, JS-rendered pages, bot blocking) and is exactly the kind of undifferentiated plumbing MCP servers already solve well. Using MCP instead of a raw SDK also means the search provider is swappable later (self-hosted SearXNG, a different vendor) without touching the agent's internal logic — only the MCP server config changes.

Revised after checking Exa's MCP server: one server instead of two. Exa's [`exa-mcp-server`](https://github.com/exa-labs/exa-mcp-server) exposes both search and page-fetch as tools (`web_search_exa`, `crawling_exa`), which covers what previously needed Tavily + Firecrawl separately. One fewer moving part, one fewer API key to manage, and Exa's search is neural/semantic rather than pure keyword — it tends to surface conceptually relevant analysis pieces for open-ended topics even when they don't share exact keywords with the query, which matters more for blog research than for a quick factual lookup.

| Server | Package | Tools used | Free tier |
|---|---|---|---|
| Exa | `exa-mcp-server` (npm, exa-labs) | `web_search_exa` (search), `crawling_exa` (full-page content for sources that need it) | 1,000 free search requests/month |

Called through a single shared `mcp_client.py` wrapper using the Python `mcp` SDK, so the Researcher module never talks to Exa's REST API directly — it calls generic `mcp_client.call_tool("exa", tool, args)`. That abstraction is what keeps this swappable (back to Tavily, or a self-hosted SearXNG later) without touching the agent's internal logic, and it's what keeps this "your architecture," not "a vendor SDK wired straight into a prompt."

**Deliberately not using:** Exa also ships `deep_researcher_start` / `deep_researcher_check` — a hosted, async "give it a question, it searches, reads, and writes a report" tool. Tempting, but it would mean Exa's own black-box agent is doing the plan → search → synthesize loop instead of ours, which is precisely the part of this project that's supposed to demonstrate our own orchestration and be visible on the dashboard step-by-step. It's noted here as a rejected option, not an oversight — worth a quick prototype-and-compare during development, but not the production path.

## 2. Where the "deep research" pattern comes from

Rather than importing a framework like GPT Researcher wholesale (Python, opinionated, hard to instrument for our own event stream), the Researcher agent borrows its **methodology** — plan sub-questions → retrieve per sub-question → extract atomic claims with citations → aggregate — and implements it natively so it can emit our `agent_events` at each step and slot into our state machine. Credit belongs to [GPT Researcher](https://github.com/assafelovic/gpt-researcher) and Stanford's [STORM](https://github.com/stanford-oval/storm) for popularizing this decompose-then-synthesize pattern; the implementation below is ours.

## 3. Pipeline

```
topic + audienceTag
   │
   ▼
[1] Query planner        — 1 LLM call  → 4-6 sub-questions
   │
   ▼
[2] Parallel search       — N MCP calls (Exa web_search_exa), concurrency-capped at 3
   │
   ▼
[3] Source filter + rank  — dedupe URLs, drop blocklisted domains, cap at ~10 sources
   │
   ▼
[4] Selective scrape      — MCP calls (Exa crawling_exa), only for top sources missing full content
   │
   ▼
[5] Claim extraction + aggregation — 1 LLM call (large context) → ResearchBrief
   │
   ▼
ResearchBrief (persisted, handed to Strategist)
```

**Step 1 — query planner.** One call to Groq `llama-3.3-70b-versatile` (fast, cheap on free tier, this is a short reasoning task). Input: topic + audience tag. Output: 4-6 sub-questions covering distinct angles — definition/background, recent developments, data/statistics, competing viewpoints, and (when `audienceTag = "UPSC"`) exam-relevance framing. Diversity of angles matters more than volume here; this is what stops the brief from being one-sided.

**Step 2 — parallel search.** One `web_search_exa` call per sub-question, `Promise.all` with a concurrency cap of 3 (Exa's documented default is 10 QPS, so 3 concurrent is conservative headroom, not a hard requirement — the real reason to cap is spreading the monthly free quota across a run rather than a single sub-question's retry burning it). Each call requests text content inline where the tool supports it, so short pages don't need a second fetch.

**Step 3 — filter + rank.** Dedupe by normalized URL across sub-questions (the same source often answers two sub-questions). Drop a small domain blocklist (content farms, SEO spam aggregators). For UPSC-audience runs, upweight `.gov`, `.edu`, PIB, and major wire services. Cap the surviving set at ~10 sources total — past that, the claim-extraction prompt gets long for little marginal benefit.

**Step 4 — selective scrape.** `web_search_exa`'s inline content is usually enough. `crawling_exa` is only invoked for sources where content came back truncated or empty (paywalled snippet, JS-heavy page) — typically 2-4 of the 10, which keeps quota usage low and avoids paying the higher per-request tier unnecessarily.

**Step 5 — claim extraction + aggregation.** This is the one place the design deliberately avoids GPT Researcher's pattern of one LLM call per source. Instead, all retrieved source text (each tagged with a `sourceId`) is stuffed into a single Gemini 2.5 Flash call — its 1M-token context comfortably holds 10 sources — and the model returns one structured JSON array of atomic claims, each tied to the `sourceId`(s) that support it, with a `contradicted` flag when two sources disagree. Collapsing this into one call instead of ten is what keeps the agent's request count low enough to survive on free-tier rate limits (see §6).

## 4. Contract

```ts
// input
interface ResearcherInput {
  runId: string;
  topic: string;
  audienceTag?: string; // e.g. "UPSC"
}

// output — this is what gets persisted and handed to the Strategist
interface ResearchBrief {
  runId: string;
  subQueries: string[];
  sources: Array<{
    id: string;
    url: string;
    title: string;
    domain: string;
    retrievedAt: string;
  }>;
  claims: Array<{
    id: string;
    text: string;
    sourceIds: string[];
    confidence: "high" | "medium" | "low";
    contradicted: boolean;
  }>;
}
```

`confidence` is set by the extraction model based on source agreement (multiple independent sources = high). `contradicted` claims are surfaced directly to the Fact-checker and, for UPSC audiences, to the Strategist as a signal to frame the topic neutrally rather than pick a side.

## 5. Database

Normalizing sources and claims into their own tables (rather than one flat `research_sources` row per claim, as in the earlier sketch) so a claim can cite multiple sources and a source can support multiple claims:

```sql
research_sources (
  id            uuid primary key,
  run_id        uuid references blog_runs(id),
  url           text not null,
  title         text,
  domain        text,
  retrieved_at  timestamptz default now()
);

research_claims (
  id            uuid primary key,
  run_id        uuid references blog_runs(id),
  claim_text    text not null,
  confidence    text check (confidence in ('high','medium','low')),
  contradicted  boolean default false
);

research_claim_sources (
  claim_id      uuid references research_claims(id),
  source_id     uuid references research_sources(id),
  primary key (claim_id, source_id)
);
```

The full `ResearchBrief` JSON is also written to `agent_steps.output` for that step — the normalized tables are for querying/joining later (e.g. the Fact-checker looks up a claim's sources directly), the jsonb blob is the source of truth for replay/debugging.

## 6. Rate-limit budget (honest accounting)

Per Researcher run: ~5 `web_search_exa` calls + 2-4 `crawling_exa` calls + 2 LLM calls (planner + extractor), all counted against Exa's shared 1,000 free requests/month. That's roughly **150-200 single-blog research runs/month** before hitting the ceiling (search + crawl draw from the same pool, hence lower than Tavily's estimate in the earlier draft, which had a separate 1,000-credit pool for scraping) — comfortable for building and demoing this assignment, not for the eventual 50-blogs/day cron, which would exhaust the monthly quota in under a week. Exa's paid tiers are metered per call type ($5-15 per 1,000 depending on search depth), so scaling to daily cron generation is a cost decision, not a rebuild — swap the API key and tier, same MCP abstraction. A self-hosted SearXNG instance remains the free fallback if budget is the constraint rather than time.

## 7. Observability events

Each emits a row to `agent_events` (see prior schema) so the dashboard shows real progress, not a spinner:

- `started`
- `planning_queries` → done: "Planned 5 research angles"
- `searching` → done: "Found 14 candidate sources across 5 searches"
- `filtering` → done: "Kept 9 sources after filtering"
- `extracting_claims` → done: "Extracted 23 claims (2 contradicted)"
- `done` / `failed` (with error detail on failure)

## 8. Error handling

- A single sub-query's search failing (timeout, 429) doesn't fail the run — it's dropped, logged, and the run proceeds with whatever sources the other sub-queries returned. The step only hard-fails if fewer than 3 total sources survive filtering — that's the minimum bar for a defensible brief.
- Claim-extraction JSON that fails to parse gets one repair retry (a follow-up prompt: "your last response wasn't valid JSON, return only the JSON array"). Second failure fails the step and surfaces in the dashboard as `needs_review`.
- MCP server unreachable (Exa down) → exponential backoff (1s, 4s), then fail the step rather than hang the run indefinitely.

## 9. Module layout

Backend for this agent is Python, not Node — using the official [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk) (`mcp` package) instead of the TS one. Pydantic models double as the runtime-validated contract and the schema fed to the LLM calls for structured output.

```
/server/agents/researcher/
  __init__.py
  runner.py              # run_researcher(input: ResearcherInput) -> ResearchBrief — orchestrates steps 1-5
  query_planner.py       # step 1
  search_client.py       # steps 2-4, wraps mcp_client calls to Exa (web_search_exa, crawling_exa)
  claim_extractor.py     # step 5
  models.py              # ResearcherInput, ResearchBrief, Claim, Source (pydantic)
  test_runner.py
  test_claim_extractor.py
/server/mcp/
  mcp_client.py           # shared MCP client bootstrap, one session per configured server
/server/db/
  schema.sql
  repositories/research_repository.py
```

Note: §4's contract is still written as TypeScript interfaces — that's the shape the orchestrator/API boundary exposes regardless of implementation language (the Next.js frontend and any other-language agents consume it as JSON either way), but the actual `ResearchBrief` type inside this module is a Pydantic model in `models.py`, not the TS interface. Say the word if you want §4 rewritten as Pydantic too.

## 10. Testing

- **Unit**: query planner output shape (given a fixture LLM response, correct sub-question count/structure); claim extractor's JSON-repair path; dedup logic on synthetic overlapping URLs.
- **Integration**: a mock MCP server returning canned Exa responses, exercising the full step 1-5 pipeline without live API calls or quota burn.
- **Edge cases to cover explicitly**: a niche topic that returns fewer than 3 sources (should hard-fail cleanly, not crash); a topic where sources disagree (contradiction flag must actually get set); an MCP server timeout mid-run (must degrade, not hang); a non-English source in the mix (extraction must not silently drop it).

---

Next: same treatment for the Strategist, once this is agreed.