"""Stage-router endpoints (research/strategist/writer/finisher): 202 shape
for the `POST` kick-off endpoints, 404 vs 409 error mapping for the `GET`
read endpoints, all against stub agents/repos via `app.dependency_overrides`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.researcher.models import Claim, ResearchBrief
from agents.strategist.models import OutlineSection, SeoPlan, StrategistOutput
from agents.writer.models import SectionResult, WriterOutput
from api import deps
from api.main import app
from db.repositories.base import RunNotFoundError
from db.repositories.errors import (
    ResearchBriefNotFoundError,
    StrategistOutputNotFoundError,
    WriterOutputNotFoundError,
)

_RUN_ROW = {"id": "run-1", "topic": "Test Topic", "audience_tag": None, "status": "done", "created_at": None}

_BRIEF = ResearchBrief(
    run_id="run-1",
    sub_queries=[],
    sources=[],
    claims=[Claim(id="claim-1", text="fact", source_ids=[], confidence="high", contradicted=False)],
)

_STRATEGY = StrategistOutput(
    run_id="run-1",
    seo_plan=SeoPlan(primary_keyword="kw", secondary_keywords=[], meta_title="t", meta_description="d", slug="s"),
    outline=[OutlineSection(section_id="intro", heading="Intro", target_keyword="kw", grounded=True, order_index=0)],
    narrative_angle="angle",
)

_WRITER_OUTPUT = WriterOutput(
    run_id="run-1",
    draft_version=1,
    sections=[
        SectionResult(
            section_id="intro",
            heading="Intro",
            body_markdown="body",
            claim_ids=["claim-1"],
            unsupported_gaps=[],
            tone_notes="",
            word_count=10,
            retries_used=0,
        )
    ],
    needs_more_research=[],
)


class _StubAgent:
    def __init__(self) -> None:
        self.calls: list = []

    async def run(self, input):
        self.calls.append(input)

    async def edit_section(self, input):
        self.calls.append(input)


class _StubRepo:
    """One stub covers every repository interface used by the stage routers
    (`get_run`, `load_research_brief`, `load_strategist_output`,
    `load_writer_output`, `load_agent_output`, `load_latest_draft`) — each
    method independently controllable via constructor flags so a single
    class can drive both the "happy path" and "missing prerequisite" tests.
    """

    def __init__(
        self,
        run=_RUN_ROW,
        research_brief=_BRIEF,
        strategist_output=_STRATEGY,
        writer_output=_WRITER_OUTPUT,
        finisher_output=None,
        latest_draft=None,
        agent_outputs=None,
    ):
        self._run = run
        self._research_brief = research_brief
        self._strategist_output = strategist_output
        self._writer_output = writer_output
        self._finisher_output = finisher_output
        self._latest_draft = latest_draft
        self._agent_outputs = agent_outputs or {}

    def get_run(self, run_id):
        if self._run is None:
            raise RunNotFoundError(f"No blog_runs row for run_id={run_id!r}")
        return self._run

    def load_research_brief(self, run_id):
        if self._research_brief is None:
            raise ResearchBriefNotFoundError("no research brief")
        return self._research_brief

    def load_strategist_output(self, run_id):
        if self._strategist_output is None:
            raise StrategistOutputNotFoundError("no strategist output")
        return self._strategist_output

    def load_writer_output(self, run_id):
        if self._writer_output is None:
            raise WriterOutputNotFoundError("no writer output")
        return self._writer_output

    def load_agent_output(self, run_id, agent):
        return self._agent_outputs.get(agent)

    def load_latest_draft(self, run_id):
        return self._latest_draft

    def list_drafts(self, run_id):
        return []


@pytest.fixture
def client():
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# --- research --------------------------------------------------------------


def test_get_research_returns_brief(client):
    app.dependency_overrides[deps.get_research_repo] = lambda: _StubRepo(
        agent_outputs={"researcher": _BRIEF.model_dump()}
    )

    response = client.get("/runs/run-1/research")

    assert response.status_code == 200
    assert response.json()["run_id"] == "run-1"


def test_get_research_404s_for_unknown_run(client):
    app.dependency_overrides[deps.get_research_repo] = lambda: _StubRepo(run=None)

    response = client.get("/runs/unknown/research")

    assert response.status_code == 404


def test_get_research_409s_when_researcher_hasnt_completed(client):
    app.dependency_overrides[deps.get_research_repo] = lambda: _StubRepo(agent_outputs={})

    response = client.get("/runs/run-1/research")

    assert response.status_code == 409


# --- strategist --------------------------------------------------------------


def test_start_strategize_returns_202(client):
    stub_agent = _StubAgent()
    app.dependency_overrides[deps.get_strategist] = lambda: stub_agent
    app.dependency_overrides[deps.get_strategist_repo] = lambda: _StubRepo()

    response = client.post("/runs/run-1/strategize", json={})

    assert response.status_code == 202
    assert len(stub_agent.calls) == 1


def test_start_strategize_409s_when_research_missing(client):
    app.dependency_overrides[deps.get_strategist] = lambda: _StubAgent()
    app.dependency_overrides[deps.get_strategist_repo] = lambda: _StubRepo(research_brief=None)

    response = client.post("/runs/run-1/strategize", json={})

    assert response.status_code == 409


def test_get_strategize_returns_output(client):
    app.dependency_overrides[deps.get_strategist_repo] = lambda: _StubRepo(
        agent_outputs={"strategist": _STRATEGY.model_dump()}
    )

    response = client.get("/runs/run-1/strategize")

    assert response.status_code == 200


# --- writer --------------------------------------------------------------


def test_start_write_returns_202(client):
    stub_agent = _StubAgent()
    app.dependency_overrides[deps.get_writer] = lambda: stub_agent
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo()

    response = client.post("/runs/run-1/write")

    assert response.status_code == 202
    assert len(stub_agent.calls) == 1


def test_start_write_409s_when_strategist_missing(client):
    app.dependency_overrides[deps.get_writer] = lambda: _StubAgent()
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo(strategist_output=None)

    response = client.post("/runs/run-1/write")

    assert response.status_code == 409


def test_get_write_returns_output(client):
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo(
        agent_outputs={"writer": _WRITER_OUTPUT.model_dump()}
    )

    response = client.get("/runs/run-1/write")

    assert response.status_code == 200


def test_get_write_drafts(client):
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo()

    response = client.get("/runs/run-1/write/drafts")

    assert response.status_code == 200
    assert response.json() == {"run_id": "run-1", "drafts": []}


# --- finisher --------------------------------------------------------------


def test_start_finish_returns_202(client):
    stub_agent = _StubAgent()
    app.dependency_overrides[deps.get_finisher] = lambda: stub_agent
    app.dependency_overrides[deps.get_finisher_repo] = lambda: _StubRepo()

    response = client.post("/runs/run-1/finish", json={})

    assert response.status_code == 202
    assert len(stub_agent.calls) == 1


def test_start_finish_409s_when_writer_missing(client):
    app.dependency_overrides[deps.get_finisher] = lambda: _StubAgent()
    app.dependency_overrides[deps.get_finisher_repo] = lambda: _StubRepo(writer_output=None)

    response = client.post("/runs/run-1/finish", json={})

    assert response.status_code == 409


def test_get_finish_409s_when_missing(client):
    app.dependency_overrides[deps.get_finisher_repo] = lambda: _StubRepo(agent_outputs={})

    response = client.get("/runs/run-1/finish")

    assert response.status_code == 409
