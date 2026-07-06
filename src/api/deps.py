"""`Depends()`-style getters.

The four agents are expensive-ish to construct (LLM client, DB engine) but
stateless and safe to share across concurrent requests, so `main.py`'s
lifespan builds one of each and stores them on `app.state`; these getters
just pull them back out per-request. Repositories are cheap (`get_engine()`
is itself `lru_cache`d) so they're constructed fresh per request instead of
also living on `app.state`.
"""

from __future__ import annotations

from fastapi import Request

from agents.finisher.finisher import Finisher
from agents.researcher.researcher import Researcher
from agents.strategist.strategist import Strategist
from agents.writer.writer import Writer
from db.engine import get_engine
from db.repositories.base import BaseAgentRepository
from db.repositories.finisher_repository import FinisherRepository
from db.repositories.research_repository import ResearchRepository
from db.repositories.resources_repository import ResourcesRepository
from db.repositories.strategist_repository import StrategistRepository
from db.repositories.writer_repository import WriterRepository


def get_researcher(request: Request) -> Researcher:
    return request.app.state.researcher


def get_strategist(request: Request) -> Strategist:
    return request.app.state.strategist


def get_writer(request: Request) -> Writer:
    return request.app.state.writer


def get_finisher(request: Request) -> Finisher:
    return request.app.state.finisher


def get_base_repo() -> BaseAgentRepository:
    """For run-level, agent-agnostic operations (`get_run`, `list_events`) —
    these live on `BaseAgentRepository` and don't require an agent-specific
    subclass.
    """
    return BaseAgentRepository(get_engine())


def get_research_repo() -> ResearchRepository:
    return ResearchRepository(get_engine())


def get_strategist_repo() -> StrategistRepository:
    return StrategistRepository(get_engine())


def get_writer_repo() -> WriterRepository:
    return WriterRepository(get_engine())


def get_finisher_repo() -> FinisherRepository:
    return FinisherRepository(get_engine())


def get_resources_repo() -> ResourcesRepository:
    return ResourcesRepository(get_engine())
