"""API-only request/response models — thin wrappers separate from each
agent's own Pydantic contracts (`ResearcherInput`, `WriterOutput`, ...),
which stay the source of truth for what gets persisted/passed between
stages. These exist purely to shape the HTTP surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator

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
    created_at: datetime | None = None


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


class StatsResponse(BaseModel):
    runs_by_status: dict[str, int]
    resource_counts: dict[str, int]
