"""Pydantic models for the Topic Generator agent: the public input/output
contract (`TopicGeneratorInput`, `TopicGeneratorOutput`, `TopicCandidate`,
`UpscSubject`, `GsPaper` — matches TOPIC_GENERATOR.md §2/§5) plus the
internal structured-output schemas for the three LLM calls (directed-mode
query expansion, candidate extraction, classification) and the dedup
tiebreak call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from agents.schema_base import StrictSchema


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
    MISCELLANEOUS_CURRENT_AFFAIRS = "miscellaneous_current_affairs"
    """Deliberate catch-all — TOPIC_GENERATOR.md §7: a bad forced tag is
    worse than an honest miscellaneous one."""


class GsPaper(str, Enum):
    GS1 = "GS1"
    GS2 = "GS2"
    GS3 = "GS3"
    GS4 = "GS4"
    ESSAY = "essay"
    PRELIMS_ONLY = "prelims_only"


class TopicGeneratorMode(str, Enum):
    AUTONOMOUS = "autonomous"
    DIRECTED = "directed"


class DedupStatus(str, Enum):
    NEW = "new"
    SIMILAR_TO_EXISTING = "similar_to_existing"
    NEEDS_REVIEW = "needs_review"


class TopicGeneratorInput(BaseModel):
    mode: TopicGeneratorMode
    user_instruction: str | None = None
    count: int = 8
    auto_approve: bool = False

    @model_validator(mode="after")
    def _directed_requires_instruction(self) -> "TopicGeneratorInput":
        if self.mode is TopicGeneratorMode.DIRECTED and not (
            self.user_instruction and self.user_instruction.strip()
        ):
            raise ValueError("user_instruction is required when mode='directed'")
        return self


class TopicCandidate(BaseModel):
    candidate_id: str
    title: str
    one_line_summary: str
    subject: UpscSubject
    gs_papers: list[GsPaper]
    why_this_topic: str
    current_relevance: str
    trigger_source_url: str | None
    dedup_status: DedupStatus
    similarity_score: float | None


class TopicGeneratorOutput(BaseModel):
    batch_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mode: TopicGeneratorMode
    candidates: list[TopicCandidate]


# --- Internal structured-output schemas ------------------------------------


class ExpandedQueries(StrictSchema):
    """Output of the directed-mode query-expansion LLM call — TOPIC_GENERATOR.md
    §3 step 1: `user_instruction` -> 2-4 concrete search queries, same pattern
    as the Researcher's `plan_queries`.
    """

    queries: list[str]


class ExtractedCandidate(StrictSchema):
    """One candidate as returned by the extraction LLM call — no `candidate_id`
    (assigned fresh per candidate in code, never by the model, same pattern as
    every other agent's code-assigned ids) and no `subject`/`gs_papers` yet
    (assigned by the separate `classify` call).
    """

    title: str
    one_line_summary: str
    trigger_source_url: str | None


class ExtractedCandidateSet(StrictSchema):
    """Output of the single `extract_candidates` LLM call — TOPIC_GENERATOR.md
    §3 step 3: one call over all search results together, batched.
    """

    candidates: list[ExtractedCandidate]


class DedupTiebreakDecision(StrictSchema):
    """Output of the borderline (similarity 0.25-0.4) dedup tiebreak call —
    TOPIC_GENERATOR.md §4."""

    same_underlying_story: bool
    reasoning: str


class ClassifiedCandidate(StrictSchema):
    """One candidate's classification, positionally zipped back onto the
    surviving candidate list in code — TOPIC_GENERATOR.md §3 step 5.
    """

    subject: UpscSubject
    gs_papers: list[GsPaper]
    why_this_topic: str
    current_relevance: str


class ClassifiedCandidateSet(StrictSchema):
    """Output of the single `classify` LLM call — one call over every
    surviving candidate together, order-preserved (index i of `classifications`
    corresponds to index i of the candidates passed into the prompt)."""

    classifications: list[ClassifiedCandidate]
