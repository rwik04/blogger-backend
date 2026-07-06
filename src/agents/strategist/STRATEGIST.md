# Strategist agent — technical design

Scope: second stage of the pipeline (`Researcher → Strategist → Writer → ...`). Takes the Researcher's `ResearchBrief` and turns it into what the Writer needs: an **outline** (section order + narrative angle) and an **SEO plan** (primary/secondary keywords, meta title/description, slug).

Revised after a simplicity check: the first draft of this doc ran keyword candidates through YAKE, KeyBERT, sentence-transformer embeddings, and a hand-rolled scoring formula before ever asking the LLM anything. That's more machinery than this step earns — an LLM given the actual research brief as grounding is genuinely good at this specific task, and every extra library is another dependency, another thing that can break, another thing to explain in review. Cut down to one LLM call plus a trivial grounding check.

## 1. The constraint that still matters

Worth keeping from the original version: there's no free, reliable real-time search-volume API. Google Keyword Planner needs an active Ads account with spend history for real numbers, Ahrefs/SEMrush are paid, and `pytrends` (the usual free workaround) is unmaintained — last release April 2023, the project page is asking for a new maintainer. So the goal isn't "find the highest-volume keyword" (that data isn't available for free), it's "find keyword phrases that are topically grounded in what was actually researched." That reframing is why leaning on the LLM is reasonable here — it doesn't need to know real volume, it needs to read the brief and describe it well.

## 2. Approach

One LLM call (Gemini 2.5 Flash — needs the full brief in context), given:
- the topic and audience tag
- every claim's `text` from the `ResearchBrief` (the actual researched content, not just the raw topic)
- the `title` + `domain` of each source in the brief (a free stand-in for "what's already ranking for this," since the Researcher's Exa calls already fetched these — no extra request)

Asked to return, in one structured JSON response: `primary_keyword`, `secondary_keywords`, `meta_title`, `meta_description`, `slug`, and the full section-by-section `outline`, each section carrying its own `heading`, `target_keyword`, and (UPSC only) `gs_paper_tag`. Keyword selection and outlining happen together instead of as two separate calls, because the outline needs keyword-awareness anyway — no reason to make the model do that reasoning twice.

**One grounding rule, enforced in the prompt, not a library**: every returned keyword must be a phrase that actually appears (verbatim or near-verbatim) in the supplied claim text or source titles. This is the cheap countermeasure to the obvious failure mode of an ungrounded LLM call — confidently inventing a plausible-sounding keyword nobody actually searches for the way the model assumes. It's an instruction, not a dependency.

**One grounding check, in plain Python, not a library**: after parsing the response, a simple case-insensitive substring check confirms each keyword phrase (or its individual significant words) shows up somewhere in the brief text passed into the prompt. This doesn't reject anything automatically — it flags ungrounded keywords with a `grounded: false` marker so they're visible on the dashboard and to the Fact-checker/Supervisor later, rather than silently trusting them. A few lines of string matching, no embeddings, no extra install.

## 3. Contract

```python
class SeoPlan(BaseModel):
    primary_keyword: str
    secondary_keywords: list[str]
    meta_title: str
    meta_description: str
    slug: str

class OutlineSection(BaseModel):
    section_id: str            # e.g. "introduction", "gs2-relevance" — matches later blog_sections.section_id
    heading: str
    target_keyword: str | None
    grounded: bool             # False if target_keyword didn't verbatim-match the brief
    gs_paper_tag: str | None   # "GS1".."GS4", UPSC only
    order_index: int

class StrategistInput(BaseModel):
    run_id: str
    research_brief: ResearchBrief
    audience_tag: str | None = None

class StrategistOutput(BaseModel):
    run_id: str
    seo_plan: SeoPlan
    outline: list[OutlineSection]
    narrative_angle: str        # one paragraph: the framing/angle chosen and why
```

## 4. Database

```sql
seo_plans (
  id                 uuid primary key,
  run_id             uuid references blog_runs(id),
  primary_keyword    text not null,
  secondary_keywords jsonb,
  meta_title         text,
  meta_description   text,
  slug               text
);

outline_sections (
  id               uuid primary key,
  run_id           uuid references blog_runs(id),
  section_id       text not null,     -- reused by blog_sections once the Writer fills content in
  heading          text not null,
  target_keyword   text,
  grounded         boolean default true,
  gs_paper_tag     text,
  order_index      integer not null
);
```

Dropped the multi-source `keyword_candidates` table from the earlier draft — there's only one source of candidates now, so a separate audit table for "which of four methods proposed this" no longer applies. `grounded` on `outline_sections` carries the equivalent signal: did this keyword actually check out against the brief.

## 5. Observability events

- `started`
- `drafting_plan` → LLM call in flight
- `plan_ready` → done: "Primary keyword + 5 secondary, 7-section outline"
- `grounding_check` → done: "6/7 keywords grounded in research" (surfaces the flag count directly, not hidden)
- `done` / `failed`

## 6. Error handling

- Response fails Pydantic validation (missing fields, malformed JSON) → one repair retry with a follow-up prompt quoting the validation error. Second failure fails the step.
- Fewer than 3 outline sections, or more than half the sections missing a `target_keyword` → same repair-retry path; the outline is the one thing downstream (Writer) can't proceed without.
- An outline can still complete successfully with some `grounded: false` keywords — that's a quality flag for the Supervisor's rubric, not a hard failure. Forcing a retry every time grounding isn't perfect would make minor keyword phrasing differences block the whole run for no real benefit.

## 7. Module layout (Python)

```
/server/agents/strategist/
  __init__.py
  runner.py            # run_strategist(input: StrategistInput) -> StrategistOutput
  strategist_llm.py    # builds the prompt, calls the model, parses + validates the response
  grounding_check.py   # plain-Python substring check, sets `grounded` per section
  models.py            # StrategistInput/Output, SeoPlan, OutlineSection
  test_strategist_llm.py
  test_grounding_check.py
/server/db/
  repositories/strategist_repository.py
```

## 8. Testing

- **Unit**: `grounding_check` against fixed input pairs (keyword present verbatim, present as a near-match, absent entirely — confirm the three cases resolve to the right `grounded` value); Pydantic validation catches a response missing `target_keyword` on a section.
- **Integration**: full run against a fixture `ResearchBrief`, asserting the retry path actually fires when the mocked LLM response is deliberately malformed on the first call and valid on the second.
- **Edge cases**: a brief with very thin claim text (near-empty research) — the model should still produce a minimal valid outline rather than erroring, even if most keywords end up `grounded: false`; a UPSC run where every claim is `contradicted` — outline must still generate with neutral framing per section, not skip the topic; an outline where the model reuses the same `target_keyword` for two sections (should be caught and is worth a warning, not a hard failure — some topical overlap between adjacent sections is normal).

---

Next: same treatment for the Writer, whenever you're ready.