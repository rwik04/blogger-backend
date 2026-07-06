"""Pydantic models for the Researcher agent: the public input/output contract
(`ResearcherInput`, `ResearchBrief`, `Claim`, `Source` — matches RESEARCHER.md
§4) plus the structured-output schemas used internally for each LLM call.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from agents.schema_base import StrictSchema

Confidence = Literal["high", "medium", "low"]


class ResearcherInput(BaseModel):
    run_id: str
    topic: str
    audience_tag: str | None = None


class Source(BaseModel):
    id: str
    url: str
    title: str
    domain: str
    retrieved_at: str


class Claim(BaseModel):
    id: str
    text: str
    source_ids: list[str]
    confidence: Confidence
    contradicted: bool = False


class ResearchBrief(BaseModel):
    run_id: str
    sub_queries: list[str]
    sources: list[Source]
    claims: list[Claim]
    report_markdown: str = ""
    """Long-form narrative report synthesized from `claims`, with inline
    `[n]` citation markers and a trailing Sources section — see
    `agents.researcher.nodes.write_report`. Empty only if that node hasn't
    run yet (e.g. reading a pre-report-feature brief from the DB)."""


# --- Internal structured-output schemas, one per LLM-calling node ----------


class PlannedSubQueries(StrictSchema):
    """Output of `plan_queries` — RESEARCHER.md §3 step 1."""

    sub_queries: list[str]


class ExtractedClaim(StrictSchema):
    """A single claim as returned by the compaction LLM call, before it's
    merged into the cumulative `claims` list (merging assigns the final `id`).
    """

    text: str
    source_ids: list[str]
    confidence: Confidence
    contradicted: bool


class SourceSummary(StrictSchema):
    source_id: str
    summary: str


class RoundCompaction(StrictSchema):
    """Output of `compact_round` — the compaction step. This is the only
    representation of a round's raw source text that survives into state;
    the raw text itself is discarded immediately after this call.

    `source_summaries` is a list (not a `dict`) deliberately: OpenAI's
    strict structured-output mode doesn't support open-ended object maps,
    only fixed schemas — see `OpenAIAdapter.reason()`.
    """

    claims: list[ExtractedClaim]
    source_summaries: list[SourceSummary]


class ReflectDecision(StrictSchema):
    """Output of `reflect_coverage`, evaluated over compacted memory only
    (never raw source text)."""

    decision: Literal["continue", "finalize"]
    reasoning: str
    next_sub_queries: list[str]
