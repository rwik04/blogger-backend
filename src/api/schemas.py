"""API-only request/response models — thin wrappers separate from each
agent's own Pydantic contracts (`ResearcherInput`, `WriterOutput`, ...),
which stay the source of truth for what gets persisted/passed between
stages. These exist purely to shape the HTTP surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator

from agents.topic_generator.models import TopicGeneratorMode
from agents.writer.models import EditPreset


class StartRunRequest(BaseModel):
    topic: str
    audience_tag: str | None = None
    run_id: str | None = None


class QueuedResponse(BaseModel):
    run_id: str
    status: str = "queued"


class RunStatusResponse(BaseModel):
    run_id: str
    topic: str
    audience_tag: str | None
    status: str
    paused: bool = False
    created_at: datetime | None = None


class RunControlResponse(BaseModel):
    """Returned by pause/resume — just enough for the client to update its
    local pause indicator without a full re-poll.
    """

    run_id: str
    paused: bool


class RunListResponse(BaseModel):
    items: list[RunStatusResponse]
    limit: int
    offset: int


class EventOut(BaseModel):
    step: str
    phase: str
    detail: dict[str, Any] | None
    created_at: datetime | None = None


class EventsResponse(BaseModel):
    run_id: str
    events: list[EventOut]


class DraftSummary(BaseModel):
    version: int
    created_by_agent: str
    created_at: datetime | None = None


class DraftsResponse(BaseModel):
    run_id: str
    drafts: list[DraftSummary]


class StrategizeRequest(BaseModel):
    audience_tag: str | None = None


class FinishRequest(BaseModel):
    include_quiz: bool | None = None


class EditSectionRequest(BaseModel):
    preset: EditPreset
    instruction: str | None = None

    @model_validator(mode="after")
    def _custom_requires_instruction(self) -> "EditSectionRequest":
        if self.preset is EditPreset.CUSTOM and not (self.instruction and self.instruction.strip()):
            raise ValueError("instruction is required when preset='custom'")
        return self


class ManualEditSectionRequest(BaseModel):
    body_markdown: str

    @model_validator(mode="after")
    def _body_not_blank(self) -> "ManualEditSectionRequest":
        if not self.body_markdown.strip():
            raise ValueError("body_markdown must not be blank")
        return self


class StatsResponse(BaseModel):
    runs_by_status: dict[str, int]
    resource_counts: dict[str, int]


class GenerateTopicsRequest(BaseModel):
    mode: TopicGeneratorMode
    user_instruction: str | None = None
    count: int = 8
    auto_approve: bool = False

    @model_validator(mode="after")
    def _directed_requires_instruction(self) -> "GenerateTopicsRequest":
        if self.mode is TopicGeneratorMode.DIRECTED and not (
            self.user_instruction and self.user_instruction.strip()
        ):
            raise ValueError("user_instruction is required when mode='directed'")
        return self


class QueuedBatchResponse(BaseModel):
    batch_id: str
    status: str = "queued"


class TopicBatchStatusResponse(BaseModel):
    batch_id: str
    mode: str
    user_instruction: str | None
    count: int
    auto_approve: bool
    status: str
    error: str | None = None
    created_at: datetime | None = None


class TopicBatchEventOut(BaseModel):
    step: str
    phase: str
    detail: dict[str, Any] | None
    created_at: datetime | None = None


class TopicBatchEventsResponse(BaseModel):
    batch_id: str
    events: list[TopicBatchEventOut]


class TopicOut(BaseModel):
    topic_id: str
    batch_id: str | None
    title: str
    one_line_summary: str | None
    subject: str | None
    gs_papers: list[str] | None
    why_this_topic: str | None
    current_relevance: str | None
    trigger_source_url: str | None
    dedup_status: str
    similarity_score: float | None
    status: str
    created_at: datetime | None = None


class TopicListResponse(BaseModel):
    items: list[TopicOut]
    limit: int
    offset: int


class SelectTopicResponse(BaseModel):
    topic_id: str
    run_id: str
    status: str = "queued"
