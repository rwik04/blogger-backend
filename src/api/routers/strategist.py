"""Strategist stage routes: kick off keyword extraction + outline planning
for a run that already has a persisted `ResearchBrief`, and read back the
resulting `StrategistOutput`.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from agents.strategist.models import StrategistInput, StrategistOutput
from agents.strategist.strategist import Strategist
from api.concurrency import run_sync
from api.deps import get_strategist, get_strategist_repo
from api.jobs import run_and_log
from api.schemas import QueuedResponse, StrategizeRequest
from db.repositories.errors import StrategistOutputNotFoundError
from db.repositories.strategist_repository import StrategistRepository

router = APIRouter(tags=["strategist"])


@router.post("/runs/{run_id}/strategize", response_model=QueuedResponse, status_code=202)
async def start_strategize(
    run_id: str,
    body: StrategizeRequest,
    background_tasks: BackgroundTasks,
    strategist: Strategist = Depends(get_strategist),
    repo: StrategistRepository = Depends(get_strategist_repo),
) -> QueuedResponse:
    run = await run_sync(repo.get_run, run_id)  # 404 if the run doesn't exist at all
    research_brief = await run_sync(repo.load_research_brief, run_id)  # 409 if Researcher hasn't completed

    audience_tag = body.audience_tag or run.get("audience_tag")
    strategist_input = StrategistInput(
        run_id=run_id,
        topic=run["topic"],
        audience_tag=audience_tag,
        research_brief=research_brief,
    )

    background_tasks.add_task(
        run_and_log, strategist.run(strategist_input), f"Strategist.run(run_id={run_id})"
    )
    return QueuedResponse(run_id=run_id)


@router.get("/runs/{run_id}/strategize", response_model=StrategistOutput)
async def get_strategize(
    run_id: str, repo: StrategistRepository = Depends(get_strategist_repo)
) -> StrategistOutput:
    await run_sync(repo.get_run, run_id)
    output = await run_sync(repo.load_agent_output, run_id, "strategist")
    if output is None:
        raise StrategistOutputNotFoundError(
            f"No persisted Strategist output for run_id={run_id!r} — run the Strategist agent first"
        )
    return StrategistOutput.model_validate(output)
