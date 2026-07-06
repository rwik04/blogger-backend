"""Run-level routes: kicking off a fresh Researcher run, listing runs, and
polling a single run's status/event trail. Stage-specific routes (research
output, strategize, write, finish) live in their own router modules.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from agents.researcher.models import ResearcherInput
from agents.researcher.researcher import Researcher
from api.deps import get_base_repo, get_researcher, get_resources_repo
from api.jobs import run_and_log
from api.schemas import (
    EventOut,
    EventsResponse,
    QueuedResponse,
    RunListResponse,
    RunStatusResponse,
    StartRunRequest,
)
from db.repositories.base import BaseAgentRepository
from db.repositories.resources_repository import ResourcesRepository

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=QueuedResponse, status_code=202)
async def start_run(
    body: StartRunRequest,
    background_tasks: BackgroundTasks,
    researcher: Researcher = Depends(get_researcher),
) -> QueuedResponse:
    run_id = body.run_id or str(uuid.uuid4())
    researcher_input = ResearcherInput(run_id=run_id, topic=body.topic, audience_tag=body.audience_tag)

    background_tasks.add_task(
        run_and_log, researcher.run(researcher_input), f"Researcher.run(run_id={run_id})"
    )
    return QueuedResponse(run_id=run_id)


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    resources_repo: ResourcesRepository = Depends(get_resources_repo),
) -> RunListResponse:
    rows = resources_repo.list_runs(limit=limit, offset=offset, status=status)
    items = [RunStatusResponse(**{**row, "run_id": str(row["run_id"])}) for row in rows]
    return RunListResponse(items=items, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(run_id: str, repo: BaseAgentRepository = Depends(get_base_repo)) -> RunStatusResponse:
    run = repo.get_run(run_id)
    return RunStatusResponse(
        run_id=str(run["id"]),
        topic=run["topic"],
        audience_tag=run.get("audience_tag"),
        status=run["status"],
        created_at=run.get("created_at"),
    )


@router.get("/runs/{run_id}/events", response_model=EventsResponse)
async def get_run_events(
    run_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    repo: BaseAgentRepository = Depends(get_base_repo),
) -> EventsResponse:
    repo.get_run(run_id)  # 404s via RunNotFoundError if the run doesn't exist at all
    events = repo.list_events(run_id, limit=limit)
    return EventsResponse(run_id=run_id, events=[EventOut(**event) for event in events])
