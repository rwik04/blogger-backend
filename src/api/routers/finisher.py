"""Finisher stage routes: kick off the SEO audit + UPSC-style quiz + media
prompt planning for a run that already has a persisted `WriterOutput`, and
read back the resulting `FinisherOutput`.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, Depends

from agents.finisher.finisher import Finisher
from agents.finisher.models import FinisherInput, FinisherOutput
from api.deps import get_finisher, get_finisher_repo
from api.jobs import run_and_log
from api.schemas import FinishRequest, QueuedResponse
from db.repositories.errors import FinisherOutputNotFoundError
from db.repositories.finisher_repository import FinisherRepository


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


router = APIRouter(tags=["finisher"])


@router.post("/runs/{run_id}/finish", response_model=QueuedResponse, status_code=202)
async def start_finish(
    run_id: str,
    body: FinishRequest,
    background_tasks: BackgroundTasks,
    finisher: Finisher = Depends(get_finisher),
    repo: FinisherRepository = Depends(get_finisher_repo),
) -> QueuedResponse:
    run = repo.get_run(run_id)  # 404 if the run doesn't exist at all
    research_brief = repo.load_research_brief(run_id)  # 409 if Researcher hasn't completed
    strategist_output = repo.load_strategist_output(run_id)  # 409 if Strategist hasn't completed
    writer_output = repo.load_writer_output(run_id)  # 409 if Writer hasn't completed

    include_quiz = body.include_quiz if body.include_quiz is not None else _env_bool(
        "FINISHER_GENERATE_QUIZ", True
    )

    finisher_input = FinisherInput(
        run_id=run_id,
        topic=run["topic"],
        audience_tag=run.get("audience_tag"),
        include_quiz=include_quiz,
        research_brief=research_brief,
        strategist_output=strategist_output,
        writer_output=writer_output,
    )

    background_tasks.add_task(run_and_log, finisher.run(finisher_input), f"Finisher.run(run_id={run_id})")
    return QueuedResponse(run_id=run_id)


@router.get("/runs/{run_id}/finish", response_model=FinisherOutput)
async def get_finish(run_id: str, repo: FinisherRepository = Depends(get_finisher_repo)) -> FinisherOutput:
    repo.get_run(run_id)
    output = repo.load_agent_output(run_id, "finisher")
    if output is None:
        raise FinisherOutputNotFoundError(
            f"No persisted Finisher output for run_id={run_id!r} — run the Finisher agent first"
        )
    return FinisherOutput.model_validate(output)
