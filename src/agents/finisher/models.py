"""Pydantic models for the Finisher agent: the public input/output contract
(`FinisherInput`, `FinisherOutput`, `SeoAudit`, `UpscStyleQuestion`,
`MediaPrompt` — matches FINISHER.md §5) plus the internal structured-output
schemas for the two LLM calls (candidate-question generation, media-prompt
generation).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from agents.researcher.models import ResearchBrief
from agents.schema_base import StrictSchema
from agents.strategist.models import StrategistOutput
from agents.writer.models import WriterOutput


QuestionType = Literal["statement_based", "direct"]
"""`statement_based` is the classic UPSC prelims format (FINISHER.md §1):
2-3 numbered statements, combination-style options. `direct` is a plain
single-answer MCQ — a straightforward question with independent answer
choices, one correct — better suited to a single checkable fact (a count,
a date, a named entity) than to a fabricated multi-statement wrapper.
Which type fits depends on the underlying claim, so `generate_candidate_questions`
produces a mix rather than defaulting every question to one format."""


class MCQOption(BaseModel):
    label: str
    text: str


class MCQStatement(BaseModel):
    text: str
    is_true: bool
    claim_id: str | None


class UpscStyleQuestion(BaseModel):
    question_id: str
    question_type: QuestionType
    stem: str
    statements: list[MCQStatement]
    """Only populated for `question_type="statement_based"` — empty for
    `"direct"` questions, which have no numbered statements to display."""
    options: list[MCQOption]
    correct_option: str
    """The label (a/b/c/d) of the correct option — for `statement_based`,
    derived from the statements' true/false pattern; for `direct`, the
    option the LLM tagged `is_correct`. Either way, assembled in
    `nodes.assemble_questions`, never asked from the LLM directly as a label."""
    explanation: str
    related_section_id: str


class SeoAudit(BaseModel):
    keyword_density: dict[str, float]
    heading_issues: list[str]
    meta_description_ok: bool
    internal_link_suggestions: list[dict]
    """`{"from_section": ..., "to_section": ..., "anchor_text": ...}` per
    FINISHER.md §5 — kept as a plain dict since it's assembled, not an LLM
    structured-output schema (the whole SEO audit is deterministic, no LLM)."""


class MediaPrompt(BaseModel):
    media_id: str
    kind: Literal["banner", "infographic"]
    section_id: str | None
    prompt: str
    alt_text: str
    image_url: str | None = None
    """Resolved by `nodes.fetch_media_images` (Google Images via SerpAPI,
    queried with `prompt`) right after `plan_media` — `None` if no
    `SERPAPI_API_KEY` is configured or the search came up empty/failed.
    Not part of FINISHER.md's original contract (which stops at the prompt),
    same pragmatic-addition pattern as `quality_flags`."""


class FinisherInput(BaseModel):
    run_id: str
    topic: str
    """Not part of FINISHER.md's strict contract — same pragmatic addition
    as `WriterInput.topic`/`StrategistInput.topic`, needed for prompt
    framing since no upstream output carries it."""
    audience_tag: str | None = None
    include_quiz: bool = True
    """Whether to run the quiz-generation steps at all — configurable via
    `FINISHER_GENERATE_QUIZ`/`--quiz`/`--no-quiz`, not part of FINISHER.md's
    contract (which assumes the quiz always runs). See `pipeline.py`'s
    conditional edge."""
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
    quality_flags: list[str]
    """Pragmatic addition beyond FINISHER.md's contract — carries §8's
    "fewer than 3 questions survived validation" signal forward (and any
    future quality signals), same reasoning as `WriterOutput.needs_more_research`.
    Empty when nothing noteworthy came up."""


# --- Internal structured-output schemas --------------------------------


class QuizRelevanceAssessment(StrictSchema):
    """Output of the `assess_quiz_relevance` LLM call — a gate that runs
    before candidate-question generation, deciding whether the topic's
    actual researched claims have enough concrete, checkable factual
    density to support a good statement-based quiz at all (as opposed to
    forcing one onto a narrative/opinion-heavy piece)."""

    quiz_relevant: bool
    reason: str


class DraftedStatement(StrictSchema):
    text: str
    is_true: bool
    claim_id: str | None


class DraftedAnswerOption(StrictSchema):
    """One answer choice for a `"direct"`-type candidate question — plain
    text plus whether it's the correct one, mirroring `DraftedStatement`'s
    true/false tagging but for independent answer choices rather than
    numbered statements. `claim_id` is required by every candidate's
    grounded-vs-not schema so OpenAI's strict JSON mode has one consistent
    shape; it's expected to be `null` on distractors that don't cite a
    specific claim (a plausible invented wrong answer needs no grounding —
    only the correct option does, checked in `nodes.validate_questions`)."""

    text: str
    is_correct: bool
    claim_id: str | None


class DraftedQuestion(StrictSchema):
    """One candidate question as returned by the LLM — no `options`/
    `correct_option`/`question_id` yet; those are assembled deterministically
    in `nodes.assemble_questions` after `nodes.validate_questions` filters
    the candidate pool.

    Exactly one of `statements` / `answer_options` is populated, matching
    `question_type` — both fields are always present (OpenAI's strict JSON
    mode requires every field, no true optionality) with the unused one an
    empty list.
    """

    question_type: QuestionType
    stem: str
    statements: list[DraftedStatement]
    answer_options: list[DraftedAnswerOption]
    explanation: str
    related_section_id: str


class DraftedQuestionSet(StrictSchema):
    """Output of the single `generate_candidate_questions` LLM call —
    FINISHER.md §2 step 1: over-generate roughly 2x the target count in one
    call rather than generating and retrying one at a time.
    """

    questions: list[DraftedQuestion]


class DraftedMediaPrompt(StrictSchema):
    kind: Literal["banner", "infographic"]
    section_id: str | None
    prompt: str
    alt_text: str


class DraftedMediaPlan(StrictSchema):
    """Output of the single `plan_media` LLM call — one banner prompt plus
    up to a couple of infographic prompts, generated together."""

    media: list[DraftedMediaPrompt]
