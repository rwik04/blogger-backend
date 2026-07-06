"""The section-edit endpoint: prerequisite validation (missing draft/section
-> 404/409), request-body validation (custom preset with no instruction ->
422), and the happy path scheduling `Writer.edit_section` as a background
task.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.researcher.models import Claim, ResearchBrief
from agents.strategist.models import OutlineSection, SeoPlan, StrategistOutput
from api import deps
from api.main import app
from db.repositories.errors import WriterOutputNotFoundError

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

_SECTIONS = [
    {
        "section_id": "intro",
        "heading": "Intro",
        "body_markdown": "text",
        "claim_ids": ["claim-1"],
        "unsupported_gaps": [],
        "tone_notes": "",
        "word_count": 1,
        "retries_used": 0,
    }
]


class _StubWriter:
    def __init__(self) -> None:
        self.calls: list = []

    async def edit_section(self, input):
        self.calls.append(input)


class _StubRepo:
    def __init__(self, latest_draft=None):
        self._latest_draft = (
            latest_draft if latest_draft is not None else {"draft_id": "d1", "version": 1, "sections": _SECTIONS}
        )

    def get_run(self, run_id):
        return _RUN_ROW

    def load_research_brief(self, run_id):
        return _BRIEF

    def load_strategist_output(self, run_id):
        return _STRATEGY

    def load_latest_draft(self, run_id):
        return self._latest_draft


@pytest.fixture
def client():
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_edit_section_returns_202_and_schedules_background_task(client):
    stub_writer = _StubWriter()
    app.dependency_overrides[deps.get_writer] = lambda: stub_writer
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo()

    response = client.post(
        "/runs/run-1/write/sections/intro/edit", json={"preset": "more_engaging"}
    )

    assert response.status_code == 202
    assert len(stub_writer.calls) == 1
    assert stub_writer.calls[0].section_id == "intro"


def test_edit_section_with_custom_preset_and_instruction_succeeds(client):
    stub_writer = _StubWriter()
    app.dependency_overrides[deps.get_writer] = lambda: stub_writer
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo()

    response = client.post(
        "/runs/run-1/write/sections/intro/edit",
        json={"preset": "custom", "instruction": "Add more stats."},
    )

    assert response.status_code == 202


def test_edit_section_with_custom_preset_and_no_instruction_is_422(client):
    app.dependency_overrides[deps.get_writer] = lambda: _StubWriter()
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo()

    response = client.post("/runs/run-1/write/sections/intro/edit", json={"preset": "custom"})

    assert response.status_code == 422


def test_edit_section_404s_for_unknown_section_id(client):
    app.dependency_overrides[deps.get_writer] = lambda: _StubWriter()
    app.dependency_overrides[deps.get_writer_repo] = lambda: _StubRepo()

    response = client.post(
        "/runs/run-1/write/sections/does-not-exist/edit", json={"preset": "more_formal"}
    )

    assert response.status_code == 404


def test_edit_section_409s_when_no_draft_exists_yet(client):
    class _NoDraftRepo(_StubRepo):
        def load_latest_draft(self, run_id):
            return None

    app.dependency_overrides[deps.get_writer] = lambda: _StubWriter()
    app.dependency_overrides[deps.get_writer_repo] = lambda: _NoDraftRepo()

    response = client.post(
        "/runs/run-1/write/sections/intro/edit", json={"preset": "more_engaging"}
    )

    assert response.status_code == 409
