"""Database resource / dashboard routes: aggregate counts across all runs
and tables, and the fully-assembled publish-ready blog for a single run.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_resources_repo
from api.schemas import StatsResponse
from db.repositories.resources_repository import ResourcesRepository

router = APIRouter(tags=["resources"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats(repo: ResourcesRepository = Depends(get_resources_repo)) -> StatsResponse:
    return StatsResponse(
        runs_by_status=repo.count_runs_by_status(),
        resource_counts=repo.count_resources(),
    )


@router.get("/runs/{run_id}/blog")
async def get_full_blog(run_id: str, repo: ResourcesRepository = Depends(get_resources_repo)) -> dict:
    blog = repo.get_full_blog(run_id)
    if blog is None:
        raise HTTPException(
            status_code=404,
            detail=f"No published blog for run_id={run_id!r} — run the Finisher agent first",
        )
    return blog
