"""Pydantic models for the Writer agent: the public input/output contract
(`WriterInput`, `WriterOutput`, `SectionResult` — matches WRITER.md §3) plus
the internal structured-output schema for the single per-section
draft+fact-check+humanize LLM call.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, model_validator

from agents.researcher.models import ResearchBrief
from agents.schema_base import StrictSchema
from agents.strategist.models import StrategistOutput


class SectionResult(BaseModel):
    section_id: str
    heading: str
    body_markdown: str
    """Final text: drafted, fact-checked, and humanized in one pass."""
    claim_ids: list[str]
    """Brief claim IDs (e.g. "claim-7") actually used and verified against —
    filtered to only those present in the brief, see `nodes.write_section`."""
    unsupported_gaps: list[str]
    """Factual details wanted but not verifiable in the brief — non-empty
    only if gaps survived both internal retries (WRITER.md §2/§8)."""
    tone_notes: str
    word_count: int
    retries_used: int
    """0-2: how many internal self-correction passes this section needed —
    the gap-retry and length-retry budgets are tracked separately in code
    (see `nodes.write_section`) but reported here as one combined count."""


class WriterInput(BaseModel):
    run_id: str
    topic: str
    """Not part of WRITER.md's strict contract, but the per-section prompt
    needs the original topic for natural framing and neither `ResearchBrief`
    nor `StrategistOutput` carries it — pulled from `blog_runs.topic` by the
    CLI/repository instead, same reasoning as `StrategistInput.topic`."""
    audience_tag: str | None = None
    research_brief: ResearchBrief
    strategist_output: StrategistOutput


class WriterOutput(BaseModel):
    run_id: str
    draft_version: int
    sections: list[SectionResult]
    needs_more_research: list[str]
    """Unresolved `unsupported_gaps`, one entry per section that still had a
    gap after exhausting retries, or that failed outright — escalation
    signal for a future Supervisor -> Researcher follow-up loop (no
    Supervisor exists yet, so this is populated but not acted upon)."""


class EditPreset(str, Enum):
    """Fixed tone-shift instructions for a one-off section rewrite, plus a
    `custom` escape hatch for a caller-supplied instruction. Non-custom
    presets may still carry an optional extra `instruction` (appended as
    additional guidance on top of the preset's fixed instruction)."""

    MORE_ENGAGING = "more_engaging"
    MORE_FORMAL = "more_formal"
    MORE_COMPREHENSIVE = "more_comprehensive"
    CUSTOM = "custom"


class EditSectionInput(BaseModel):
    run_id: str
    topic: str
    audience_tag: str | None = None
    research_brief: ResearchBrief
    strategist_output: StrategistOutput
    section_id: str
    preset: EditPreset
    instruction: str | None = None

    @model_validator(mode="after")
    def _custom_requires_instruction(self) -> "EditSectionInput":
        if self.preset is EditPreset.CUSTOM and not (self.instruction and self.instruction.strip()):
            raise ValueError("instruction is required when preset='custom'")
        return self


# --- Internal structured-output schema for write_section --------------------


class DraftedSection(StrictSchema):
    """Output of the single per-section LLM call — WRITER.md §2: draft,
    self-fact-check, and humanize happen together in one structured
    response. `word_count`/`retries_used` are computed in code, never asked
    from the model, same pattern as the Strategist's `grounded` field.
    """

    body_markdown: str
    claim_ids: list[str]
    unsupported_gaps: list[str]
    tone_notes: str
