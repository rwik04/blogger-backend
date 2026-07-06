"""Run-level routes: kicking off a fresh Researcher run, listing runs, and
polling a single run's status/event trail. Stage-specific routes (research
output, strategize, write, finish) live in their own router modules.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from api.concurrency import run_sync
from api.deps import get_base_repo, get_resources_repo, get_supervisor
from api.jobs import run_and_log
from api.schemas import (
    EventOut,
    EventsResponse,
    QueuedResponse,
    RunControlResponse,
    RunListResponse,
    RunStatusResponse,
    StartRunRequest,
)
from api.supervisor import PipelineSupervisor
from db.repositories.base import BaseAgentRepository
from db.repositories.resources_repository import ResourcesRepository

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=QueuedResponse, status_code=202)
async def start_run(
    body: StartRunRequest,
    background_tasks: BackgroundTasks,
    supervisor: PipelineSupervisor = Depends(get_supervisor),
) -> QueuedResponse:
    run_id = body.run_id or str(uuid.uuid4())

    # Same "Generate Blog" entry point as topic selection — Researcher runs
    # first, then the supervisor auto-advances through the rest of the
    # pipeline unless the run is paused.
    background_tasks.add_task(
        run_and_log,
        supervisor.start(run_id, topic=body.topic, audience_tag=body.audience_tag),
        f"PipelineSupervisor.start(run_id={run_id})",
    )
    return QueuedResponse(run_id=run_id)


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    resources_repo: ResourcesRepository = Depends(get_resources_repo),
) -> RunListResponse:
    rows = await run_sync(resources_repo.list_runs, limit=limit, offset=offset, status=status)
    items = [RunStatusResponse(**{**row, "run_id": str(row["run_id"])}) for row in rows]
    return RunListResponse(items=items, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(run_id: str, repo: BaseAgentRepository = Depends(get_base_repo)) -> RunStatusResponse:
    run = await run_sync(repo.get_run, run_id)
    return RunStatusResponse(
        run_id=str(run["id"]),
        topic=run["topic"],
        audience_tag=run.get("audience_tag"),
        status=run["status"],
        paused=bool(run.get("paused", False)),
        created_at=run.get("created_at"),
    )


@router.get("/runs/{run_id}/events", response_model=EventsResponse)
async def get_run_events(
    run_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    repo: BaseAgentRepository = Depends(get_base_repo),
) -> EventsResponse:
    await run_sync(repo.get_run, run_id)  # 404s via RunNotFoundError if the run doesn't exist at all
    events = await run_sync(repo.list_events, run_id, limit=limit)
    return EventsResponse(run_id=run_id, events=[EventOut(**event) for event in events])


@router.post("/runs/{run_id}/pause", response_model=RunControlResponse)
async def pause_run(run_id: str, repo: BaseAgentRepository = Depends(get_base_repo)) -> RunControlResponse:
    """Stops the supervisor's auto-advance chain at the next stage boundary.
    Does not interrupt a stage that's already running — see `api.supervisor`.
    """
    await run_sync(repo.get_run, run_id)  # 404s via RunNotFoundError if the run doesn't exist at all
    await run_sync(repo.set_paused, run_id, True)
    return RunControlResponse(run_id=run_id, paused=True)


@router.post("/runs/{run_id}/resume", response_model=RunControlResponse)
async def resume_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    repo: BaseAgentRepository = Depends(get_base_repo),
    supervisor: PipelineSupervisor = Depends(get_supervisor),
) -> RunControlResponse:
    """Clears the pause flag and, if the run is idle at a stage boundary,
    immediately continues the pipeline from wherever it left off.
    """
    await run_sync(repo.get_run, run_id)  # 404s via RunNotFoundError if the run doesn't exist at all
    await run_sync(repo.set_paused, run_id, False)
    background_tasks.add_task(run_and_log, supervisor.resume(run_id), f"PipelineSupervisor.resume(run_id={run_id})")
    return RunControlResponse(run_id=run_id, paused=False)
