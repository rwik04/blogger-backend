"""Read-only access to a run's persisted Researcher output. Kicking off the
Researcher itself is `POST /runs` (see `routers/runs.py`) — there's no
`POST /runs/{run_id}/research` since the Researcher is what creates the run
in the first place.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.researcher.models import ResearchBrief
from api.deps import get_research_repo
from db.repositories.errors import ResearchBriefNotFoundError
from db.repositories.research_repository import ResearchRepository

router = APIRouter(tags=["research"])


@router.get("/runs/{run_id}/research", response_model=ResearchBrief)
async def get_research(run_id: str, repo: ResearchRepository = Depends(get_research_repo)) -> ResearchBrief:
    repo.get_run(run_id)  # 404s if the run doesn't exist at all
    output = repo.load_agent_output(run_id, "researcher")
    if output is None:
        raise ResearchBriefNotFoundError(
            f"No persisted Researcher output for run_id={run_id!r} — run the Researcher agent first"
        )
    return ResearchBrief.model_validate(output)
