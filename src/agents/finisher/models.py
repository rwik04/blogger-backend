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


class MCQOption(BaseModel):
    label: str
    text: str


class MCQStatement(BaseModel):
    text: str
    is_true: bool
    claim_id: str | None


class UpscStyleQuestion(BaseModel):
    question_id: str
    stem: str
    statements: list[MCQStatement]
    options: list[MCQOption]
    correct_option: str
    """The label (a/b/c/d) of the option matching the statements' true/false
    pattern — derived deterministically in `nodes.assemble_questions`, never
    asked from the LLM."""
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


class DraftedStatement(StrictSchema):
    text: str
    is_true: bool
    claim_id: str | None


class DraftedQuestion(StrictSchema):
    """One candidate question as returned by the LLM — no `options`/
    `correct_option`/`question_id` yet; those are assembled deterministically
    in `nodes.assemble_questions` after `nodes.validate_questions` filters
    the candidate pool.
    """

    stem: str
    statements: list[DraftedStatement]
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
