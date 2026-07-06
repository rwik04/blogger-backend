# Topic generator — technical design

Scope: a new stage that sits **before** the Researcher, and the first point where a human actually looks at something before the pipeline commits to a full run. Until now every design in this series assumed the topic just arrives. This is where topics get proposed, justified, and classified — the user picks one (or the system auto-picks, for the eventual cron), and that becomes the input to the Researcher exactly as before.

This is also where the UPSC-audience framing formally re-enters the system. `audience_tag` has been sitting as a dormant, unused field on every agent's input since the Strategist redesign — this is where it actually gets populated, from real classification, instead of being invented downstream.

## 1. Two modes, one pipeline

- **Directed**: the user gives a steering instruction ("topics about the judiciary," "something in environmental policy this month") and the generator searches within that direction.
- **Autonomous**: no steering — the generator sweeps recent developments across the UPSC subject areas itself and surfaces whatever's most current and least-covered.

Both modes share every step after query construction. The only difference is how the initial search queries get built (§3, step 1) — everything downstream (extraction, dedup, classification, justification) is identical, so this is one agent with two entry paths, not two agents.

A third axis, orthogonal to the two modes above: `auto_approve`. Off by default — candidates are surfaced for the user to look at and pick, which is the explicit ask here. On, for the future cron use case — the top-ranked candidate is taken automatically and fed straight into the Researcher with no human in the loop. Same generation and justification logic either way; this flag only decides whether a human sees the list first.

## 2. The classification enums

Checked the actual UPSC Mains structure rather than approximating it. Two separate enums, because real current-affairs content usually needs both — a Prelims-facing subject tag (what topic area is this) and a Mains GS-paper tag (which paper would use this), and a single story often maps to more than one GS paper (a Supreme Court ruling on free speech is both GS1-adjacent society and GS2 polity):

```python
class UpscSubject(str, Enum):
    POLITY_GOVERNANCE = "polity_governance"
    ECONOMY = "economy"
    ENVIRONMENT_ECOLOGY = "environment_ecology"
    SCIENCE_TECHNOLOGY = "science_technology"
    GEOGRAPHY = "geography"
    HISTORY_CULTURE = "history_culture"
    INTERNATIONAL_RELATIONS = "international_relations"
    SOCIAL_JUSTICE = "social_justice"
    ETHICS = "ethics"
    SECURITY_DISASTER_MGMT = "security_disaster_management"
    MISCELLANEOUS_CURRENT_AFFAIRS = "miscellaneous_current_affairs"  # deliberate catch-all, see §7

class GsPaper(str, Enum):
    GS1 = "GS1"     # heritage, culture, history, society, geography
    GS2 = "GS2"     # governance, constitution, polity, social justice, international relations
    GS3 = "GS3"     # economy, science & tech, environment, agriculture, security, disaster management
    GS4 = "GS4"     # ethics, integrity, aptitude
    ESSAY = "essay"
    PRELIMS_ONLY = "prelims_only"   # doesn't map cleanly onto any Mains GS paper
```

A candidate's `gs_papers` field is a list, not a single value, for exactly the multi-mapping reason above.

## 3. Pipeline

```
mode + (user_instruction if directed)
   │
   ▼
[1] Query construction
      autonomous: rotate through UpscSubject values, one lightweight search per subject
      directed:   one LLM call expands user_instruction into 2-4 concrete search queries
                  (same pattern as the Researcher's query planner — proven design, reused)
   │
   ▼
[2] Lightweight search (Exa MCP, web_search_exa) — shallow, top 5 results per query,
    no crawling/full-page extraction. This is a scan for candidate stories, not the
    deep multi-source research the Researcher does once a topic is actually chosen.
   │
   ▼
[3] Candidate extraction — one LLM call over all search results together,
    returns N distinct topic candidates (title + one-line summary + trigger source URL)
   │
   ▼
[4] Dedup filter — deterministic, against topic history (§5), before spending
    any more LLM budget on candidates that are just repeats
   │
   ▼
[5] Classification + justification — one LLM call, over all surviving candidates
    together, assigns subject + gs_papers + why_this_topic + current_relevance
   │
   ▼
TopicCandidate[] → surfaced to the user (or auto-selected if auto_approve)
```

Two LLM calls total (extraction, classification) regardless of how many subjects were searched or how many candidates survive — batching across all candidates in one call each, rather than one call per candidate, is the same lesson applied here as in the Strategist's simplification: an LLM given the full context in one shot is both simpler and cheaper than N small calls.

## 4. Dedup — trigram similarity, not embeddings

Consistent with keeping the stack simple: no sentence-transformers here either. Postgres's built-in `pg_trgm` extension computes trigram text similarity directly in SQL — `similarity(candidate.title, topics.title)` — against every previously generated topic's title. No model download, no embedding step, no new Python dependency.

- Similarity ≥ 0.4 against any historical topic → dropped as a duplicate, not surfaced.
- Similarity 0.25-0.4 → genuinely ambiguous (same words, possibly different angle) — these specific borderline pairs, and only these, get a single cheap LLM tiebreak call ("are these the same underlying story or a genuinely new angle on it?"). Most candidates never reach this step; it only fires on the ambiguous middle band.
- Below 0.25 → treated as new.

This mirrors the grounding-check pattern from the Strategist and Finisher docs: cheap deterministic check first, LLM only where the deterministic check is genuinely inconclusive.

## 5. Contract

```python
class TopicGeneratorMode(str, Enum):
    AUTONOMOUS = "autonomous"
    DIRECTED = "directed"

class TopicGeneratorInput(BaseModel):
    mode: TopicGeneratorMode
    user_instruction: str | None = None    # required when mode == DIRECTED
    count: int = 8
    auto_approve: bool = False

class TopicCandidate(BaseModel):
    candidate_id: str
    title: str
    one_line_summary: str
    subject: UpscSubject
    gs_papers: list[GsPaper]
    why_this_topic: str          # the value case: why an aspirant should care
    current_relevance: str       # why now, tied to the actual trigger story
    trigger_source_url: str | None
    dedup_status: str            # "new" | "similar_to_existing" | "needs_review"
    similarity_score: float | None

class TopicGeneratorOutput(BaseModel):
    generated_at: datetime
    mode: TopicGeneratorMode
    candidates: list[TopicCandidate]
```

Once the user (or `auto_approve`) selects a candidate, its `title`, `subject`, and `gs_papers` become the `topic` and `audience_tag` on the existing `ResearcherInput` — no changes needed to the Researcher's contract, this just finally fills in the field that was left dormant.

## 6. Database

```sql
create extension if not exists pg_trgm;

topics (
  id                  uuid primary key,
  title               text not null,
  slug                text,
  subject             text,               -- UpscSubject value
  gs_papers           jsonb,              -- array of GsPaper values
  why_this_topic      text,
  current_relevance   text,
  trigger_source_url  text,
  status              text check (status in ('suggested','selected','generated','rejected')) default 'suggested',
  created_at          timestamptz default now()
);

create index topics_title_trgm_idx on topics using gin (title gin_trgm_ops);
```

`blog_runs.topic_id` (already in the original schema sketch) references this table — a run's topic was always meant to trace back to something, this is what actually populates it now instead of a bare string.

## 7. Observability events

- `started` (mode + instruction, if directed)
- `searching` → done: "Scanned 5 subject areas" / "Expanded instruction into 4 queries"
- `extracting_candidates` → done: "Found 11 candidate topics"
- `dedup_check` → done: "3 dropped as duplicates, 1 flagged for review, 7 new"
- `classifying` → done: "Tagged 7 candidates across GS1-GS3"
- `done`

## 8. Error handling

- Directed mode with no `user_instruction` → validation error at input, doesn't silently fall back to autonomous.
- A subject/query in autonomous mode returns zero fresh results (a quiet news day for that subject) → skip it, don't fail the batch. Not every subject needs a candidate every run.
- Every candidate in a batch comes back `similar_to_existing` → don't return an empty list. Retry once with a diversity nudge in the extraction prompt ("avoid these already-covered angles: [...]"), then return whatever survives even if some are still flagged — never hide results from the user, let them see and override the flag themselves.
- A candidate that doesn't fit any `UpscSubject` well gets `MISCELLANEOUS_CURRENT_AFFAIRS` rather than being force-fit into the nearest wrong category — the enum has a deliberate catch-all for exactly this, and a bad forced tag is worse than an honest miscellaneous one.

## 9. Module layout (Python)

```
/server/agents/topic_generator/
  __init__.py
  runner.py               # run_topic_generator(input) -> TopicGeneratorOutput
  query_builder.py        # autonomous subject rotation OR directed instruction expansion
  candidate_extractor.py  # step 3, one LLM call
  dedup_filter.py         # pg_trgm check + borderline LLM tiebreak
  classifier.py           # step 5, one LLM call across all surviving candidates
  models.py               # enums, TopicCandidate, TopicGeneratorInput/Output
  test_dedup_filter.py
  test_classifier.py
/server/db/
  repositories/topic_repository.py
```

## 10. Testing

- **Unit**: `dedup_filter`'s trigram thresholds against three fixed cases (obvious duplicate, genuinely ambiguous near-match, clearly unrelated); `classifier` output validated against the enum values, with a repair retry if the model returns a subject string outside `UpscSubject`.
- **Integration**: fixture Exa search results through the full pipeline in both modes, asserting every surviving candidate has non-empty `why_this_topic` and `current_relevance`, and that directed mode without `user_instruction` fails validation before any search happens.
- **Edge cases**: an autonomous run on a slow news day where 4 of 6 subjects return nothing usable (must still produce candidates from the other 2, not fail outright); a directed instruction that's a poor UPSC fit ("topics about cooking") — should classify to `MISCELLANEOUS_CURRENT_AFFAIRS` rather than force a GS tag, and that's a legitimate output, not an error; a candidate that trigram-matches an old topic closely but is actually a genuine follow-up development (e.g., a court case's next hearing) — this is exactly what the borderline LLM tiebreak in §4 exists to catch, worth a specific test that it doesn't get auto-dropped by the deterministic threshold alone.

---

This is also a good point to note that the earlier pipeline diagrams now have a node before the Researcher that isn't drawn — worth redrawing once this is agreed, same as the note left after the Writer merge.