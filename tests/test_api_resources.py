"""Database resource endpoints: `GET /stats` and `GET /runs/{run_id}/blog`,
against a stub `ResourcesRepository`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import app


class _StubResourcesRepo:
    def __init__(self, runs_by_status=None, resource_counts=None, full_blog=None):
        self._runs_by_status = runs_by_status or {"done": 3, "running": 1}
        self._resource_counts = resource_counts or {"blog_drafts": 3, "published_blogs_staged": 1}
        self._full_blog = full_blog

    def count_runs_by_status(self):
        return self._runs_by_status

    def count_resources(self):
        return self._resource_counts

    def get_full_blog(self, run_id):
        return self._full_blog


@pytest.fixture
def client():
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_get_stats_returns_counts(client):
    app.dependency_overrides[deps.get_resources_repo] = lambda: _StubResourcesRepo()

    response = client.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["runs_by_status"] == {"done": 3, "running": 1}
    assert body["resource_counts"]["blog_drafts"] == 3


def test_get_full_blog_returns_assembled_blog(client):
    full_blog = {
        "run_id": "run-1",
        "final_title": "Title",
        "final_tags": ["tag"],
        "subject": "sports",
        "published_at": None,
        "canonical_url": None,
        "draft_version": 1,
        "sections": [],
        "questions": [],
        "media": [],
        "seo_audit": None,
    }
    app.dependency_overrides[deps.get_resources_repo] = lambda: _StubResourcesRepo(full_blog=full_blog)

    response = client.get("/runs/run-1/blog")

    assert response.status_code == 200
    assert response.json()["final_title"] == "Title"


def test_get_full_blog_404s_when_finisher_hasnt_completed(client):
    app.dependency_overrides[deps.get_resources_repo] = lambda: _StubResourcesRepo(full_blog=None)

    response = client.get("/runs/run-1/blog")

    assert response.status_code == 404
