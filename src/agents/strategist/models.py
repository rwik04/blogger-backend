"""Pydantic models for the Strategist agent: the public input/output contract
(`StrategistInput`, `StrategistOutput`, `SeoPlan`, `OutlineSection` — matches
STRATEGIST.md §3) plus the internal structured-output schema for the single
`draft_plan` LLM call.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.researcher.models import ResearchBrief
from agents.schema_base import StrictSchema


class SeoPlan(BaseModel):
    primary_keyword: str
    secondary_keywords: list[str]
    meta_title: str
    meta_description: str
    slug: str


class OutlineSection(BaseModel):
    section_id: str
    heading: str
    target_keyword: str | None
    grounded: bool
    order_index: int


class StrategistInput(BaseModel):
    run_id: str
    topic: str
    """Not part of STRATEGIST.md's strict contract, but the `draft_plan`
    prompt needs the original topic and `ResearchBrief` doesn't carry it —
    pulled from `blog_runs.topic` by the CLI/repository instead."""
    research_brief: ResearchBrief
    audience_tag: str | None = None


class StrategistOutput(BaseModel):
    run_id: str
    seo_plan: SeoPlan
    outline: list[OutlineSection]
    narrative_angle: str


# --- Internal structured-output schema for draft_plan -----------------------


class DraftedOutlineSection(StrictSchema):
    """One outline section as returned by the LLM — no `grounded` field yet;
    that's computed afterward in `nodes.grounding_check`, never by the model.
    """

    section_id: str
    heading: str
    target_keyword: str | None
    order_index: int


class DraftedPlan(StrictSchema):
    """Output of the single `draft_plan` LLM call — STRATEGIST.md §2: keyword
    selection and outlining happen together in one structured response.
    """

    primary_keyword: str
    secondary_keywords: list[str]
    meta_title: str
    meta_description: str
    slug: str
    narrative_angle: str
    outline: list[DraftedOutlineSection]
