# Finisher agent — technical design

Scope: last stage before the Supervisor's review, in the now-four-node pipeline (`Researcher → Strategist → Writer → Finisher → Supervisor`). Takes the finished, fact-checked, humanized draft and does everything needed to make it publishable: an SEO audit, the interactive quiz, media prompts, and final front matter. This doc spends most of its length on the quiz, since it has the most specific requirement — questions need to actually read like UPSC prelims questions, not generic trivia with four options.

## 1. What "UPSC-style" means, specifically

Checked the actual format rather than going off a vague impression of "multiple choice." UPSC prelims MCQs are overwhelmingly **statement-based**: roughly 60% of prelims questions present 2-3 numbered statements and ask "Which of the statements given above is/are correct?", with combination-style options rather than four independent answer choices. A real example, for calibration:

> Consider the following statements:
> 1. When the Lok Sabha is dissolved, any bill pending in the Lok Sabha automatically lapses.
> 2. If a bill has been passed by the Lok Sabha but is pending in the Rajya Sabha, it lapses upon the dissolution of the Lok Sabha.
> 3. A bill regarding which the President has notified a joint sitting will not lapse on the dissolution of the Lok Sabha.
>
> Which of the statements given above is/are correct?
> (a) 1 and 3 only  (b) 2 only  (c) 1, 2 and 3  (d) 3 only

That combination-option structure (`1 only` / `2 only` / `Both 1 and 2` / `Neither 1 nor 2` for two statements; `1 and 2 only` / `2 and 3 only` / `1 and 3 only` / `1, 2 and 3` for three) is the thing that makes this format distinctly harder to generate correctly than a plain MCQ — the model has to get every individual statement's truth value right, because the "correct" option is derived from the *combination*, not asserted directly. One wrong statement silently produces a wrong answer key. This drives most of the design below.

One useful, concrete heuristic surfaced during research: absolute language (*always, never, only, completely, must, entirely, every time*) is a common tell for a deliberately false statement in real UPSC questions — worth baking into the generation prompt as guidance, since it's how the real exam writes plausible-but-wrong statements rather than obviously silly ones.

The other ~40% of prelims questions (and virtually all quiz content once you're not narrowly reproducing prelims) are **direct, single-answer MCQs**: a plain question with 3-4 independent answer choices, one correct — "How many teams will compete in the 2026 FIFA World Cup?" with choices "32" / "40" / "48" / "64". Forcing a single checkable fact (a count, a date, a name) through the statement/combination format produces an artificial-feeling question with padding statements that don't add anything; a `direct` question is the better fit there. `question_type` (`"statement_based"` | `"direct"`) is decided per-candidate in step 1, mixing both across a run rather than defaulting every question to one format.

## 2. Quiz generation pipeline

```
Finished draft (WriterOutput) + ResearchBrief claims
   │
   ▼
[0] Relevance gate        — LLM call: does this topic's claims have enough concrete,
                             checkable factual density to support a good statement-based
                             quiz at all? If not, skip straight to media planning — a
                             narrative/opinion-heavy topic forced into MCQ form produces
                             weak or overreaching questions, worse than no quiz.
   │
   ▼
[1] Candidate generation  — LLM call: 2x the target question count, each with
                             2-3 statements individually tagged true/false + claim_id
   │
   ▼
[2] Grounding validation  — every statement tagged "true" must match a claim's text;
                             every statement tagged "false" must contradict or overstate one
                             (not just be unrelated — an unrelated false statement is a weak question)
   │
   ▼
[3] Option assembly       — deterministic, not LLM: derive the correct combination-option
                             from the validated true/false tags, generate 3 plausible distractor
                             combinations
   │
   ▼
[4] Selection             — pick 3-5 final questions spanning distinct sections
                             (never all from section 1), drop anything that failed validation
   │
   ▼
UpscStyleQuestion[]
```

**Step 0 — relevance gate, distinct from the `include_quiz` on/off toggle.** `include_quiz` is a user/config-level "I want a quiz for this run"; the relevance gate is the Finisher's own judgment on whether the topic actually supports one. One cheap LLM call sees the topic, section headings, and the researched claims themselves and returns `quiz_relevant: bool` plus a one-sentence `reason`. Skipping here (rather than always over-generating and letting validation/selection drop everything) avoids wasting the candidate-generation call on topics that were never going to produce good statement-based questions — diplomatic-goodwill pieces, opinion columns, human-interest framing — and surfaces *why* via a `quality_flags` entry (`"Quiz skipped — not relevant for this topic: <reason>"`) rather than silently returning zero questions the way an `include_quiz=False` run does.

**Step 1 — over-generate, mixing both question types.** Ask for roughly double the target count (say 8 candidates for a 4-question target) in one call. Each candidate carries `question_type`; a `statement_based` candidate has its statements individually tagged with which claim they're based on, a `direct` candidate has its own answer choices with one tagged `is_correct` and (for that correct one) which claim it cites. Over-generating up front is cheaper than generating one at a time and retrying — most quality loss happens at validation, so having spare candidates to select from beats regenerating from scratch.

**Step 2 — grounding validation, the same discipline as the Strategist's keyword grounding, branched by type.** No LLM call either way — plain text comparison between each answer and the claim it cites. For `statement_based`: a statement tagged `is_true: true` whose claim_id doesn't exist, or whose text doesn't actually support the statement, fails validation — the direct defense against the failure mode named in §1, a wrong true/false tag silently producing a wrong answer key. For `direct`: exactly one option must be tagged correct, and that correct option must closely match its cited claim (distractors need no grounding — they're supposed to be wrong, and don't need a `claim_id` at all). Failing candidates are dropped, not repaired — repairing a single statement inside an already-assembled multi-statement question risks fixing one statement while leaving the option combination stale, and there's no cheaper partial-repair story for a bad direct MCQ either.

**Step 3 — option assembly is deterministic, not generated, but the shape differs by type.** For `statement_based`: once statements are validated true/false, the correct option is just "which combination of numbers is true" — computing that from tags is a lookup, not something to trust an LLM to get right under the same failure mode that got us here. Distractor options are the other 3 combinations from the same statement set, so all four options are always internally consistent in structure (never a nonsense option like "1 and 4 only" on a 3-statement question). For `direct`: the LLM already wrote the actual option texts in step 1 (validated in step 2), so assembly is just shuffling a/b/c/d labels onto them and reading off which one was tagged correct — no lookup table involved.

**Step 4 — selection.** From the surviving validated candidates, pick 3-5 that span distinct `section_id`s (matches the assignment's "1-5 MCQs" range and the earlier `#quiz-{runId}-q{n}` element-ID scheme from the frontend design). If fewer than 3 candidates survive validation, that's a real quality signal — see §6.

## 3. SEO audit (deterministic, no LLM)

Runs against the assembled draft + `SeoPlan` from the Strategist: keyword density for `primary_keyword` and each `secondary_keyword` (simple word-count ratio, flagged if under ~0.5% or over ~3%), heading hierarchy check (one H1, sequential H2s, no skipped levels), meta description length (120-160 characters, the standard SERP-snippet range), and internal cross-link suggestions — sections whose `target_keyword`s are semantically close (reusing the outline's keyword assignments from the Strategist, no new embedding step needed) get suggested as "link section X to section Y" pairs for the frontend to render as intra-links.

## 4. Media prompts

For the banner and any inline infographics, generate a short image-generation prompt plus alt text per asset, anchored to a `section_id` where relevant (matches the `#media-{slug}-banner` / `#media-{slug}-infographic-{n}` ID scheme from the frontend design). This stage doesn't call an image-generation API itself — it produces the prompt and alt text; actual image generation is a separate concern (a later integration decision, not blocking this design).

## 5. Contract

```python
class MCQOption(BaseModel):
    label: str          # "a" | "b" | "c" | "d"
    text: str           # e.g. "1 and 3 only"

class MCQStatement(BaseModel):
    text: str
    is_true: bool
    claim_id: str | None

class UpscStyleQuestion(BaseModel):
    question_id: str
    question_type: Literal["statement_based", "direct"]
    stem: str                        # statement-based: "Consider the following statements about X:"
                                      # direct: the actual question, e.g. "How many teams will compete in...?"
    statements: list[MCQStatement]   # 2-3 statements; empty for "direct"
    options: list[MCQOption]         # combination-style for statement_based, plain answer choices for direct
    correct_option: str              # label, derived deterministically in step 3
    explanation: str                 # grounded in the cited claim(s)
    related_section_id: str

class SeoAudit(BaseModel):
    keyword_density: dict[str, float]
    heading_issues: list[str]
    meta_description_ok: bool
    internal_link_suggestions: list[dict]   # {from_section, to_section, anchor_text}

class MediaPrompt(BaseModel):
    media_id: str
    kind: str            # "banner" | "infographic"
    section_id: str | None
    prompt: str
    alt_text: str

class FinisherInput(BaseModel):
    run_id: str
    research_brief: ResearchBrief
    strategist_output: StrategistOutput
    writer_output: WriterOutput

class FinisherOutput(BaseModel):
    run_id: str
    seo_audit: SeoAudit
    questions: list[UpscStyleQuestion]
    media: list[MediaPrompt]
    final_title: str
    final_tags: list[str]
    subject: str
```

## 6. Database

```sql
seo_audits (
  id                       uuid primary key,
  run_id                   uuid references blog_runs(id),
  keyword_density          jsonb,
  heading_issues           jsonb,
  meta_description_ok      boolean,
  internal_link_suggestions jsonb
);

quiz_questions (
  id                 uuid primary key,
  run_id             uuid references blog_runs(id),
  question_type      text not null default 'statement_based',  -- 'statement_based' | 'direct'
  stem               text not null,
  statements         jsonb not null,   -- [{text, is_true, claim_id}], empty for 'direct'
  options            jsonb not null,
  correct_option     text not null,
  explanation        text,
  related_section_id text
);

media_assets (
  id           uuid primary key,
  run_id       uuid references blog_runs(id),
  kind         text check (kind in ('banner','infographic')),
  section_id   text,
  prompt       text,
  alt_text     text,
  status       text default 'pending'
);

published_blogs (
  id             uuid primary key,
  run_id         uuid references blog_runs(id),
  final_title    text,
  tags           jsonb,
  subject        text,
  published_at   timestamptz,
  canonical_url  text
);
```

## 7. Observability events

- `started`
- `auditing_seo` → done: "Keyword density OK, 1 heading issue, 2 internal links suggested"
- `assessing_quiz_relevance` → done: "relevant — specific dates, named institutions, and numeric figures throughout" (or "not relevant — ...")
- `generating_questions` → done: "8 candidate questions drafted"
- `validating_questions` → done: "5/8 passed grounding, selected 4 across 4 sections"
- `planning_media` → done: "1 banner + 2 infographic prompts"
- `done` / `failed`

## 8. Error handling

- Fewer than 3 candidate questions survive grounding validation → not a hard failure, but a quality flag surfaced to the Supervisor (this is the kind of thing that should route back to the Writer if the underlying sections just don't have enough checkable factual density — a narrative-heavy draft with few concrete claims will struggle to produce good statement-based questions, and that's a drafting problem, not a Finisher problem).
- A validated question's derived correct option matches more than one of the four generated distractors (a real risk if the distractor-generation logic in step 3 doesn't exclude the true combination) → regenerate distractors for that question only, deterministic fix, no LLM call needed.
- SEO audit failures (density out of range, missing meta) don't block Finisher's completion — they're data for the Supervisor's rubric, same as the original design intent for this stage.

## 9. Module layout (Python)

```
/server/agents/finisher/
  __init__.py
  runner.py             # run_finisher(input: FinisherInput) -> FinisherOutput
  quiz_generator.py      # step 1: candidate statement-based questions
  quiz_validator.py      # step 2: grounding check
  quiz_assembler.py      # step 3-4: deterministic option assembly + selection
  seo_auditor.py         # keyword density, heading, meta, internal links
  media_planner.py       # banner/infographic prompts
  models.py
  test_quiz_validator.py
  test_quiz_assembler.py
  test_seo_auditor.py
/server/db/
  repositories/finisher_repository.py
```

## 10. Testing

- **Unit**: `quiz_assembler`'s combination-option logic against all 2-statement and 3-statement cases (verify the correct option always matches the true/false tags exactly, and the 3 distractors are always the *other* combinations, never a repeat of the correct one); `quiz_validator` correctly fails a statement whose claim_id doesn't exist and correctly fails a "false" statement that doesn't actually contradict anything; keyword density calculator against known word counts.
- **Integration**: fixture `WriterOutput` + `ResearchBrief` through the full pipeline, asserting the final question set has internally consistent options and every statement traces to a real claim or is correctly marked false against one.
- **Edge cases**: a draft where only 2 sections have enough factual density for statement-based questions (must still hit the 3-question soft minimum by drawing multiple questions from those 2 sections rather than forcing weak questions from the rest); a candidate question where two of its statements are logical duplicates (should be caught in validation, not just left in); a topic where every claim is `contradicted` in the brief (writing a *false* statement here is easy, writing a defensible *true* one is hard — worth a specific test that validation still holds up under low-certainty source material).

---

Next: the Supervisor is really the only piece left to formalize — the routing logic was sketched in the dependency-graph diagrams earlier, so that doc would mostly be about turning that into an actual rubric and state machine.