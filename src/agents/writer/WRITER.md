# Writer agent — technical design (v2: drafting + fact-checking + humanizing, merged)

Scope: third stage of the pipeline. Supersedes the earlier version of this doc, which treated drafting as the Writer's only job and left fact-checking and humanizing as two separate downstream agents. Per the decision to consolidate: **one agent now drafts, verifies, and polishes each section together**, instead of three agents passing a full draft back and forth in large round trips.

## 1. Why merge, and what changes

The original three-agent design (Writer → Fact-checker → Humanizer) worked at the level of the *whole draft*: write everything, then fact-check everything, then humanize everything. That has a real cost — by the time the Fact-checker flags a problem in section 2, the Writer has already moved on and written sections 3 through 7 around it, so a correction to section 2 risks needing to ripple forward. Handling accuracy and tone **per section, at write time**, avoids that entirely: a section isn't considered finished until it's already factually checked and already reads naturally, so nothing downstream is ever built on a shaky section.

This does trade away something real: three focused single-purpose passes each doing one job well versus one pass doing three jobs at once, which risks shallower treatment of each. The mitigation is keeping the three concerns structurally visible in the output even though they're produced together (see the contract below) — so the merge saves round trips without becoming a black box.

**Ripple effect on the pipeline graph**: the six-node pipeline collapses to four (`Researcher → Strategist → Writer → Finisher → Supervisor`), and the Supervisor's revision routing (previously three targets: Fact-checker, Humanizer, Finisher) simplifies to two: **Writer** (covers both factual and tone issues now) and **Finisher** (structure/SEO/quiz issues), plus Publish. Worth redrawing the earlier dependency diagrams once this is locked in — flagging it here rather than leaving the old diagrams silently wrong.

## 2. Per-section loop, now doing three things at once

Still sequential, for the same reason as before — section 3 needs to know what section 2 said. What changes is what happens *inside* each section's turn:

```
for each outline section, in order:
   │
   ▼
[1] One LLM call: draft + self-fact-check + humanize, together
      given: outline, full claims list, draft-so-far, this section's heading + target_keyword
      returns: body_markdown, claim_ids used, unsupported_gaps, tone_notes
   │
   ▼
[2] If unsupported_gaps is non-empty:
      → up to 2 internal retries on this same section
        (rephrase around the gap, or drop the unverifiable detail)
   │
   ▼
[3] Section accepted — gaps that survived 2 retries are logged, not blocking
      (they become the signal for a possible Writer → Researcher escalation, see §4)
   │
   ▼
append to draft-so-far, move to next section
```

The single call is instructed to do three things in sequence *within its own reasoning*, not asked to blend them into one vague pass: draft the section against the outline and claims; check every factual statement it just wrote against the supplied claims and either keep only what's supported or flag what isn't; then rewrite the checked draft for natural tone — vary sentence length, don't open by restating the heading, avoid stock AI transitions ("in today's world," "it's important to note"). Asking for this as an explicit three-step instruction, and asking the model to return the outcome of each step, is what keeps the merge from becoming genuinely opaque.

## 3. Contract

```python
class SectionResult(BaseModel):
    section_id: str            # matches StrategistOutput's OutlineSection.section_id
    heading: str
    body_markdown: str         # final text: drafted, fact-checked, humanized
    claim_ids: list[str]       # brief claims actually used and verified against
    unsupported_gaps: list[str]  # factual details wanted but not verifiable in the brief
    tone_notes: str            # short self-report of what changed for humanizing (audit trail)
    word_count: int
    retries_used: int          # 0-2, how many internal self-correction passes this section needed

class WriterInput(BaseModel):
    run_id: str
    research_brief: ResearchBrief
    strategist_output: StrategistOutput

class WriterOutput(BaseModel):
    run_id: str
    draft_version: int
    sections: list[SectionResult]
    needs_more_research: list[str]   # unresolved unsupported_gaps, escalated for the Supervisor
```

`needs_more_research` is the direct replacement for the old Fact-checker → Researcher loop edge — it's populated only from gaps that survived both internal retries, so it's a genuinely rare, meaningful signal rather than routine noise.

## 4. Escalation path (what replaces the old Fact-checker → Researcher loop)

The merged Writer has no search capability, so it can't resolve a genuinely missing fact itself — that's still the Researcher's job. When `needs_more_research` is non-empty on the `WriterOutput`, the Supervisor (per the updated routing diagram) can send the run back to the **Researcher** with those specific gap descriptions as targeted follow-up queries, rather than a full re-run of the research step. This keeps the one edge from the old graph that a single merged agent genuinely can't absorb, while everything that used to be a Fact-checker-driven or Humanizer-driven revision loop now resolves inside the Writer's own per-section retry, invisibly to the rest of the pipeline.

## 5. Model choice

Unchanged from the earlier draft of this doc, and more relevant now: Gemini 2.5 Flash, not Groq. Each call is doing more work per section (draft + verify + humanize in one instruction, larger structured output), and the prompt still grows with the draft-so-far across sequential calls — both push token usage per call higher than a single-purpose call would, which is exactly the profile that risks Groq's 12K tokens/minute free-tier ceiling. Gemini's context headroom matters more, not less, now that one call carries three jobs.

## 6. Database

```sql
blog_drafts (
  id               uuid primary key,
  run_id           uuid references blog_runs(id),
  version          integer not null,
  created_by_agent text not null,   -- 'writer' — always, since this agent now owns the full loop
  created_at       timestamptz default now()
);

blog_sections (
  id                uuid primary key,
  draft_id          uuid references blog_drafts(id),
  section_id        text not null,
  heading           text not null,
  body_markdown     text not null,
  order_index       integer not null,
  word_count        integer,
  tone_notes        text,
  retries_used      integer default 0,
  unsupported_gaps  jsonb           -- gaps logged even if not escalated
);

blog_section_claims (
  section_id       uuid references blog_sections(id),
  claim_id         uuid references research_claims(id),
  primary key (section_id, claim_id)
);
```

The standalone `fact_check_flags` table from the original three-agent schema sketch is retired — `blog_sections.unsupported_gaps` and `blog_section_claims` together cover what it used to track, now scoped to the agent that actually owns fact-checking.

## 7. Observability events

- `started`
- `writing_section` → per section, done: "Section 3/7 drafted, checked, and polished (312 words, 2 claims, 0 gaps)"
- `section_retry` → only fires when `unsupported_gaps` triggers an internal retry: "Section 5 retry 1/2 — reworking unverifiable claim about X"
- `done` → "Draft complete: 7 sections, 1,540 words, 1 unresolved gap flagged for research"
- `failed`

The `section_retry` event matters most for the "state visible on the UI" requirement — it's the one place this merged agent is doing self-correction, and it should be visibly happening, not silently absorbed.

## 8. Error handling

- `unsupported_gaps` non-empty after 2 internal retries → accept the section, log the gap, add it to `needs_more_research`. Never block the whole run on one unverifiable detail.
- Section body under ~50 words after the combined pass → one additional retry with an explicit minimum-length instruction (separate budget from the fact-gap retries — a too-short section isn't the same failure mode).
- Two consecutive section failures (not the same section retrying, but two *different* sections both failing outright) → fail the step. A broken section in the draft-so-far corrupts every section after it, same reasoning as the original design.

## 9. Module layout (Python)

```
/server/agents/writer/
  __init__.py
  runner.py            # run_writer(input: WriterInput) -> WriterOutput — sequential section loop + retry logic
  section_writer.py    # builds the draft+check+humanize prompt for one section, parses the structured response
  models.py            # WriterInput/Output, SectionResult
  test_runner.py
  test_section_writer.py
/server/db/
  repositories/writer_repository.py
```

## 10. Testing

- **Unit**: the internal retry trigger fires only when `unsupported_gaps` is non-empty, and stops at 2 attempts even if gaps persist; `claim_ids` validator strips any ID not present in the brief; short-section retry logic uses a separate counter from the gap-retry logic (both must be independently testable, since §8 keeps their budgets separate).
- **Integration**: fixture outline + brief with a mocked LLM that returns `unsupported_gaps` on section 4's first two attempts and a clean result on the third accepted-as-is pass — assert `needs_more_research` ends up populated and `retries_used` reads 2.
- **Edge cases**: a section where the humanizing rewrite accidentally drops a previously-verified claim from `body_markdown` (the text and the `claim_ids` list disagreeing is a real risk of merging three concerns into one call — worth an explicit check that every claimed `claim_id` actually has corresponding text in the body); a run where every section needs at least one retry (make sure total call count stays bounded and doesn't quietly become 3x the sequential calls the rate-limit budget assumed); a single-section outline with a gap on that only section (must still populate `needs_more_research` correctly with just one section run).

---

Next: same treatment for the Finisher, whenever you're ready.