"""Database resource / dashboard routes: aggregate counts across all runs
and tables, and the fully-assembled publish-ready blog for a single run.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from api.concurrency import run_sync
from api.deps import get_resources_repo
from api.schemas import StatsResponse
from db.repositories.resources_repository import ResourcesRepository

router = APIRouter(tags=["resources"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats(repo: ResourcesRepository = Depends(get_resources_repo)) -> StatsResponse:
    # Independent queries — run on separate pool connections in parallel
    # rather than paying for two sequential round-trips.
    runs_by_status, resource_counts = await asyncio.gather(
        run_sync(repo.count_runs_by_status),
        run_sync(repo.count_resources),
    )
    return StatsResponse(runs_by_status=runs_by_status, resource_counts=resource_counts)


@router.get("/runs/{run_id}/blog")
async def get_full_blog(run_id: str, repo: ResourcesRepository = Depends(get_resources_repo)) -> dict:
    blog = await run_sync(repo.get_full_blog, run_id)
    if blog is None:
        raise HTTPException(
            status_code=404,
            detail=f"No published blog for run_id={run_id!r} — run the Finisher agent first",
        )
    return blog
