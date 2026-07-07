"""Writer stage routes: kick off per-section drafting for a run that already
has a persisted `StrategistOutput`, read back the latest `WriterOutput` and
draft version history, and rewrite a single section with a tone preset or
custom instruction (persisted as a new draft version).
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from agents.writer.models import EditSectionInput, WriterInput, WriterOutput
from agents.writer.writer import Writer
from api.concurrency import run_sync
from api.deps import get_writer, get_writer_repo
from api.jobs import run_and_log
from api.schemas import DraftsResponse, DraftSummary, EditSectionRequest, ManualEditSectionRequest, QueuedResponse
from db.repositories.errors import SectionNotFoundError, WriterOutputNotFoundError
from db.repositories.writer_repository import WriterRepository

router = APIRouter(tags=["writer"])


@router.post("/runs/{run_id}/write", response_model=QueuedResponse, status_code=202)
async def start_write(
    run_id: str,
    background_tasks: BackgroundTasks,
    writer: Writer = Depends(get_writer),
    repo: WriterRepository = Depends(get_writer_repo),
) -> QueuedResponse:
    run = await run_sync(repo.get_run, run_id)  # 404 if the run doesn't exist at all
    research_brief = await run_sync(repo.load_research_brief, run_id)  # 409 if Researcher hasn't completed
    strategist_output = await run_sync(repo.load_strategist_output, run_id)  # 409 if Strategist hasn't completed

    writer_input = WriterInput(
        run_id=run_id,
        topic=run["topic"],
        audience_tag=run.get("audience_tag"),
        research_brief=research_brief,
        strategist_output=strategist_output,
    )

    background_tasks.add_task(run_and_log, writer.run(writer_input), f"Writer.run(run_id={run_id})")
    return QueuedResponse(run_id=run_id)


@router.get("/runs/{run_id}/write", response_model=WriterOutput)
async def get_write(run_id: str, repo: WriterRepository = Depends(get_writer_repo)) -> WriterOutput:
    await run_sync(repo.get_run, run_id)
    output = await run_sync(repo.load_agent_output, run_id, "writer")
    if output is None:
        raise WriterOutputNotFoundError(
            f"No persisted Writer output for run_id={run_id!r} — run the Writer agent first"
        )
    return WriterOutput.model_validate(output)


@router.get("/runs/{run_id}/write/drafts", response_model=DraftsResponse)
async def get_write_drafts(run_id: str, repo: WriterRepository = Depends(get_writer_repo)) -> DraftsResponse:
    await run_sync(repo.get_run, run_id)
    drafts = await run_sync(repo.list_drafts, run_id)
    return DraftsResponse(run_id=run_id, drafts=[DraftSummary(**draft) for draft in drafts])


@router.post(
    "/runs/{run_id}/write/sections/{section_id}/edit",
    response_model=QueuedResponse,
    status_code=202,
)
async def edit_section_route(
    run_id: str,
    section_id: str,
    body: EditSectionRequest,
    background_tasks: BackgroundTasks,
    writer: Writer = Depends(get_writer),
    repo: WriterRepository = Depends(get_writer_repo),
) -> QueuedResponse:
    run = await run_sync(repo.get_run, run_id)
    research_brief = await run_sync(repo.load_research_brief, run_id)
    strategist_output = await run_sync(repo.load_strategist_output, run_id)

    latest_draft = await run_sync(repo.load_latest_draft, run_id)
    if latest_draft is None:
        raise WriterOutputNotFoundError(
            f"No persisted draft for run_id={run_id!r} — run the Writer agent first"
        )
    if not any(s["section_id"] == section_id for s in latest_draft["sections"]):
        raise SectionNotFoundError(f"section_id={section_id!r} not found in latest draft (run_id={run_id!r})")

    edit_input = EditSectionInput(
        run_id=run_id,
        topic=run["topic"],
        audience_tag=run.get("audience_tag"),
        research_brief=research_brief,
        strategist_output=strategist_output,
        section_id=section_id,
        preset=body.preset,
        instruction=body.instruction,
    )

    background_tasks.add_task(
        run_and_log,
        writer.edit_section(edit_input),
        f"Writer.edit_section(run_id={run_id}, section_id={section_id})",
    )
    return QueuedResponse(run_id=run_id)


@router.put(
    "/runs/{run_id}/write/sections/{section_id}",
    response_model=WriterOutput,
)
async def manual_edit_section_route(
    run_id: str,
    section_id: str,
    body: ManualEditSectionRequest,
    writer: Writer = Depends(get_writer),
    repo: WriterRepository = Depends(get_writer_repo),
) -> WriterOutput:
    # No LLM call here — just a direct overwrite, so unlike the AI-edit
    # route above this runs synchronously and returns the updated output
    # right away instead of a 202-queued background task.
    await run_sync(repo.get_run, run_id)
    return await writer.manual_edit_section(run_id, section_id, body.body_markdown)
