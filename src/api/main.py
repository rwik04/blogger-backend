"""FastAPI app exposing the four pipeline agents (Researcher, Strategist,
Writer, Finisher) plus run-level and database-resource endpoints.

Execution model: every mutating (`POST`) endpoint does a fast synchronous
prerequisite check (does the run exist? has the previous stage completed?),
schedules the actual agent call as a background task, and returns
`202 {run_id, status: "queued"}` immediately. Clients poll `GET /runs/{run_id}`
and `GET /runs/{run_id}/events` for progress, backed by `blog_runs.status`
and `agent_events` — the same tables every agent already writes to via the
CLI, so no new job-tracking table is needed.

Run with:
    uv run serve-api
    uv run uvicorn api.main:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents.finisher.finisher import Finisher
from agents.researcher.researcher import Researcher
from agents.strategist.strategist import Strategist
from agents.topic_generator.topic_generator import TopicGenerator
from agents.writer.writer import Writer
from api.routers import finisher, research, resources, runs, strategist, topics, writer
from api.scheduler import is_cron_enabled, run_daily_topic_cron
from api.supervisor import PipelineSupervisor
from db.engine import get_engine, warm_pool
from db.repositories.base import RunNotFoundError
from db.repositories.errors import (
    AgentOutputNotFoundError,
    SectionNotFoundError,
    TopicBatchNotFoundError,
    TopicNotFoundError,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Every blocking repository call in every route handler goes through
    # `asyncio.to_thread` (see `api/concurrency.py`), which by default runs
    # on `asyncio`'s default executor — capped at `min(32, cpu_count + 4)`
    # workers. That's smaller than `DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW`
    # connections the DB pool can actually hand out, so under concurrent
    # load requests were queuing for a free *thread* well before they'd ever
    # queue for a free *connection*. Size the executor to the DB pool
    # instead of Python's generic default.
    from db.settings import DatabaseSettings

    db_settings = DatabaseSettings.from_env()
    executor_size = max(db_settings.pool_size + db_settings.max_overflow, 8)
    asyncio.get_event_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=executor_size, thread_name_prefix="db-worker")
    )

    # Build (and warm) the pooled DB engine first, before anything else
    # touches it — `get_engine()` is process-wide/`lru_cache`d, so every
    # repository built later (per-request, in `api.deps`) reuses this same
    # already-warm pool instead of each lazily opening its own first
    # connection on whatever request happens to need it first.
    engine = await asyncio.to_thread(get_engine)
    warmed = await asyncio.to_thread(warm_pool, engine)
    logger.info("DB connection pool warmed (%d connection(s))", warmed)

    # Each agent's __init__ is cheap (LLM client + a pooled DB engine handle),
    # and every agent is stateless across calls, so one instance per process
    # is safe to share across concurrent requests.
    app.state.researcher = Researcher.from_env()
    app.state.strategist = Strategist.from_env()
    app.state.writer = Writer.from_env()
    app.state.finisher = Finisher.from_env()
    app.state.topic_generator = TopicGenerator.from_env()
    app.state.supervisor = PipelineSupervisor(
        researcher=app.state.researcher,
        strategist=app.state.strategist,
        writer=app.state.writer,
        finisher=app.state.finisher,
    )

    cron_task: asyncio.Task | None = None
    if is_cron_enabled():
        cron_task = asyncio.create_task(run_daily_topic_cron(app.state.topic_generator))
    else:
        logger.info("Daily topic cron disabled (TOPIC_CRON_ENABLED not set)")

    yield

    if cron_task is not None:
        cron_task.cancel()
        try:
            await cron_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Blogger Pipeline API", lifespan=lifespan)

# The frontend calls this API directly from the browser, so it needs an
# explicit allow-list rather than the default same-origin-only behavior.
# Local dev origins are always allowed; extra origins (e.g. the deployed
# frontend's public URL) can be added via CORS_EXTRA_ORIGINS without a
# code change.
_extra_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        *_extra_origins,
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RunNotFoundError)
async def run_not_found_handler(request: Request, exc: RunNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SectionNotFoundError)
async def section_not_found_handler(request: Request, exc: SectionNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AgentOutputNotFoundError)
async def agent_output_not_found_handler(request: Request, exc: AgentOutputNotFoundError) -> JSONResponse:
    # The run exists but a prerequisite stage hasn't completed yet — a
    # conflict with the current state of the run, not a missing resource.
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(TopicBatchNotFoundError)
async def topic_batch_not_found_handler(request: Request, exc: TopicBatchNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(TopicNotFoundError)
async def topic_not_found_handler(request: Request, exc: TopicNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


app.include_router(runs.router)
app.include_router(research.router)
app.include_router(strategist.router)
app.include_router(writer.router)
app.include_router(finisher.router)
app.include_router(resources.router)
app.include_router(topics.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    """Entry point for the `serve-api` script — runs uvicorn programmatically
    so `uv run serve-api` works without a separate uvicorn invocation.
    """
    import os

    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
        reload=bool(os.environ.get("API_RELOAD")),
    )


if __name__ == "__main__":
    main()
