"""Run-level API routes: kicking off a Researcher run, listing/polling runs,
and reading the event trail — all against stub agents/repos via
`app.dependency_overrides`, no live LLM/DB.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from db.repositories.base import RunNotFoundError


class _StubResearcher:
    def __init__(self) -> None:
        self.calls: list = []

    async def run(self, input):
        self.calls.append(input)


class _StubBaseRepo:
    def __init__(self, runs: dict, events: dict | None = None):
        self._runs = runs
        self._events = events or {}

    def get_run(self, run_id):
        if run_id not in self._runs:
            raise RunNotFoundError(f"No blog_runs row for run_id={run_id!r}")
        return self._runs[run_id]

    def list_events(self, run_id, limit=50):
        return self._events.get(run_id, [])[:limit]


class _StubResourcesRepo:
    def __init__(self, rows):
        self._rows = rows

    def list_runs(self, limit=50, offset=0, status=None):
        rows = self._rows
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return rows[offset : offset + limit]


@pytest.fixture
def client():
    # Deliberately not used as a context manager: entering it would run the
    # app's `lifespan` (building real agents via `.from_env()`, which needs
    # OPENAI_API_KEY/DB_* to actually be set in the process env). Every route
    # under test here has its dependencies overridden below, so the app
    # startup step is never needed.
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_start_run_returns_202_and_schedules_background_task(client):
    stub_researcher = _StubResearcher()
    app.dependency_overrides[deps.get_researcher] = lambda: stub_researcher

    response = client.post("/runs", json={"topic": "FIFA World Cup 2026"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert "run_id" in body
    assert len(stub_researcher.calls) == 1
    assert stub_researcher.calls[0].topic == "FIFA World Cup 2026"


def test_start_run_honors_explicit_run_id(client):
    stub_researcher = _StubResearcher()
    app.dependency_overrides[deps.get_researcher] = lambda: stub_researcher

    response = client.post("/runs", json={"topic": "Topic", "run_id": "my-run-id"})

    assert response.status_code == 202
    assert response.json()["run_id"] == "my-run-id"


def test_get_run_returns_run_status(client):
    repo = _StubBaseRepo(
        {"run-1": {"id": "run-1", "topic": "T", "audience_tag": None, "status": "done", "created_at": None}}
    )
    app.dependency_overrides[deps.get_base_repo] = lambda: repo

    response = client.get("/runs/run-1")

    assert response.status_code == 200
    assert response.json()["status"] == "done"


def test_get_run_404s_for_unknown_run(client):
    repo = _StubBaseRepo({})
    app.dependency_overrides[deps.get_base_repo] = lambda: repo

    response = client.get("/runs/unknown-run")

    assert response.status_code == 404


def test_get_run_events(client):
    repo = _StubBaseRepo(
        {"run-1": {"id": "run-1", "topic": "T", "audience_tag": None, "status": "done", "created_at": None}},
        events={"run-1": [{"step": "write_section", "phase": "done", "detail": None, "created_at": None}]},
    )
    app.dependency_overrides[deps.get_base_repo] = lambda: repo

    response = client.get("/runs/run-1/events")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run-1"
    assert len(body["events"]) == 1
    assert body["events"][0]["step"] == "write_section"


def test_list_runs_is_paginated_and_filters_by_status(client):
    rows = [
        {"run_id": "r1", "topic": "T1", "audience_tag": None, "status": "done", "created_at": None},
        {"run_id": "r2", "topic": "T2", "audience_tag": None, "status": "running", "created_at": None},
    ]
    app.dependency_overrides[deps.get_resources_repo] = lambda: _StubResourcesRepo(rows)

    response = client.get("/runs", params={"status": "done"})

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["run_id"] == "r1"
