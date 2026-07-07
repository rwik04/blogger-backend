"""Routes for the Topic Generator stage: kicking off a batch (autonomous or
directed), polling its status/events, browsing persisted candidates, and
selecting one to actually start a Researcher run from.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response

from agents.topic_generator.models import TopicGeneratorInput
from agents.topic_generator.topic_generator import TopicGenerator
from api.concurrency import run_sync
from api.deps import get_supervisor, get_topic_generator, get_topic_repo
from api.jobs import run_and_log
from api.supervisor import PipelineSupervisor
from api.schemas import (
    GenerateTopicsRequest,
    QueuedBatchResponse,
    SelectTopicResponse,
    TopicBatchEventOut,
    TopicBatchEventsResponse,
    TopicBatchStatusResponse,
    TopicListResponse,
    TopicOut,
)
from db.repositories.topic_repository import TopicRepository

router = APIRouter(tags=["topics"])


@router.post("/topics/generate", response_model=QueuedBatchResponse, status_code=202)
async def generate_topics(
    body: GenerateTopicsRequest,
    background_tasks: BackgroundTasks,
    topic_generator: TopicGenerator = Depends(get_topic_generator),
) -> QueuedBatchResponse:
    batch_id = str(uuid.uuid4())
    generator_input = TopicGeneratorInput(
        mode=body.mode,
        user_instruction=body.user_instruction,
        count=body.count,
        auto_approve=body.auto_approve,
    )

    background_tasks.add_task(
        run_and_log,
        topic_generator.run(generator_input, batch_id=batch_id),
        f"TopicGenerator.run(batch_id={batch_id})",
    )
    return QueuedBatchResponse(batch_id=batch_id)


@router.get("/topics/batches/{batch_id}", response_model=TopicBatchStatusResponse)
async def get_batch(batch_id: str, repo: TopicRepository = Depends(get_topic_repo)) -> TopicBatchStatusResponse:
    batch = await run_sync(repo.get_batch, batch_id)
    return TopicBatchStatusResponse(
        batch_id=str(batch["id"]),
        mode=batch["mode"],
        user_instruction=batch.get("user_instruction"),
        count=batch["count"],
        auto_approve=batch["auto_approve"],
        status=batch["status"],
        error=batch.get("error"),
        created_at=batch.get("created_at"),
    )


@router.get("/topics/batches/{batch_id}/events", response_model=TopicBatchEventsResponse)
async def get_batch_events(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    repo: TopicRepository = Depends(get_topic_repo),
) -> TopicBatchEventsResponse:
    await run_sync(repo.get_batch, batch_id)  # 404s via TopicBatchNotFoundError if the batch doesn't exist at all
    events = await run_sync(repo.list_batch_events, batch_id, limit=limit)
    return TopicBatchEventsResponse(batch_id=batch_id, events=[TopicBatchEventOut(**event) for event in events])


def _to_topic_out(row: dict) -> TopicOut:
    return TopicOut(
        topic_id=str(row["id"]),
        batch_id=str(row["batch_id"]) if row.get("batch_id") else None,
        title=row["title"],
        one_line_summary=row.get("one_line_summary"),
        subject=row.get("subject"),
        gs_papers=row.get("gs_papers"),
        why_this_topic=row.get("why_this_topic"),
        current_relevance=row.get("current_relevance"),
        trigger_source_url=row.get("trigger_source_url"),
        dedup_status=row["dedup_status"],
        similarity_score=row.get("similarity_score"),
        status=row["status"],
        created_at=row.get("created_at"),
    )


@router.get("/topics", response_model=TopicListResponse)
async def list_topics(
    status: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: TopicRepository = Depends(get_topic_repo),
) -> TopicListResponse:
    rows = await run_sync(repo.list_topics, status=status, subject=subject, limit=limit, offset=offset)
    return TopicListResponse(items=[_to_topic_out(row) for row in rows], limit=limit, offset=offset)


@router.get("/topics/{topic_id}", response_model=TopicOut)
async def get_topic(topic_id: str, repo: TopicRepository = Depends(get_topic_repo)) -> TopicOut:
    row = await run_sync(repo.get_topic, topic_id)
    return _to_topic_out(row)


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(topic_id: str, repo: TopicRepository = Depends(get_topic_repo)) -> Response:
    await run_sync(repo.delete_topic, topic_id)  # 404s via TopicNotFoundError if missing
    return Response(status_code=204)


@router.post("/topics/{topic_id}/select", response_model=SelectTopicResponse, status_code=202)
async def select_topic(
    topic_id: str,
    background_tasks: BackgroundTasks,
    repo: TopicRepository = Depends(get_topic_repo),
    supervisor: PipelineSupervisor = Depends(get_supervisor),
) -> SelectTopicResponse:
    topic = await run_sync(repo.get_topic, topic_id)  # 404s via TopicNotFoundError if missing
    await run_sync(repo.mark_topic_selected, topic_id)

    run_id = str(uuid.uuid4())

    # "Generate Blog" is a single entry point, not four separate button
    # clicks — the supervisor runs Researcher and then keeps going through
    # Strategist/Writer/Finisher on its own (pausable at any stage boundary
    # via `POST /runs/{run_id}/pause`).
    background_tasks.add_task(
        run_and_log,
        supervisor.start(run_id, topic=topic["title"], audience_tag="UPSC", topic_id=topic_id),
        f"PipelineSupervisor.start(run_id={run_id}, topic_id={topic_id})",
    )
    return SelectTopicResponse(topic_id=topic_id, run_id=run_id)
