"""`/topics*` routes: 202 shapes for the kick-off/select endpoints, 404
mapping for unknown batches/topics, and `GET /topics` filtering — mirrors
`test_api_pipeline_endpoints.py`'s stub-agent/stub-repo + dependency
override pattern.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from db.repositories.errors import TopicBatchNotFoundError, TopicNotFoundError

_BATCH_ROW = {
    "id": "batch-1",
    "mode": "autonomous",
    "user_instruction": None,
    "count": 8,
    "auto_approve": False,
    "status": "done",
    "error": None,
    "created_at": None,
}

_TOPIC_ROW = {
    "id": "topic-1",
    "batch_id": "batch-1",
    "title": "Supreme Court ruling on free speech",
    "one_line_summary": "A summary.",
    "subject": "polity_governance",
    "gs_papers": ["GS2"],
    "why_this_topic": "why",
    "current_relevance": "relevance",
    "trigger_source_url": None,
    "dedup_status": "new",
    "similarity_score": None,
    "status": "suggested",
    "created_at": None,
}


class _StubTopicGenerator:
    def __init__(self):
        self.calls: list = []

    async def run(self, input, batch_id=None):
        self.calls.append((input, batch_id))


class _StubResearcher:
    def __init__(self):
        self.calls: list = []

    async def run(self, input):
        self.calls.append(input)


class _StubTopicRepo:
    def __init__(self, batch=_BATCH_ROW, topic=_TOPIC_ROW, topics=None):
        self._batch = batch
        self._topic = topic
        self._topics = topics if topics is not None else [_TOPIC_ROW]
        self.selected: list[str] = []
        self.list_calls: list[dict] = []

    def get_batch(self, batch_id):
        if self._batch is None:
            raise TopicBatchNotFoundError(f"No topic_batches row for batch_id={batch_id!r}")
        return self._batch

    def list_batch_events(self, batch_id, limit=50):
        return []

    def get_topic(self, topic_id):
        if self._topic is None:
            raise TopicNotFoundError(f"No topics row for topic_id={topic_id!r}")
        return self._topic

    def list_topics(self, status=None, subject=None, limit=50, offset=0):
        self.list_calls.append({"status": status, "subject": subject, "limit": limit, "offset": offset})
        return self._topics

    def mark_topic_selected(self, topic_id):
        self.selected.append(topic_id)


@pytest.fixture
def client():
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_generate_topics_autonomous_returns_202(client):
    stub_generator = _StubTopicGenerator()
    app.dependency_overrides[deps.get_topic_generator] = lambda: stub_generator

    response = client.post("/topics/generate", json={"mode": "autonomous"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert "batch_id" in body
    assert len(stub_generator.calls) == 1


def test_generate_topics_directed_without_instruction_422s(client):
    app.dependency_overrides[deps.get_topic_generator] = lambda: _StubTopicGenerator()

    response = client.post("/topics/generate", json={"mode": "directed"})

    assert response.status_code == 422


def test_generate_topics_directed_with_instruction_returns_202(client):
    stub_generator = _StubTopicGenerator()
    app.dependency_overrides[deps.get_topic_generator] = lambda: stub_generator

    response = client.post(
        "/topics/generate", json={"mode": "directed", "user_instruction": "Recent SC rulings", "count": 5}
    )

    assert response.status_code == 202
    assert len(stub_generator.calls) == 1


def test_get_batch_returns_status(client):
    app.dependency_overrides[deps.get_topic_repo] = lambda: _StubTopicRepo()

    response = client.get("/topics/batches/batch-1")

    assert response.status_code == 200
    assert response.json()["batch_id"] == "batch-1"


def test_get_batch_404s_for_unknown_batch(client):
    app.dependency_overrides[deps.get_topic_repo] = lambda: _StubTopicRepo(batch=None)

    response = client.get("/topics/batches/unknown")

    assert response.status_code == 404


def test_get_batch_events_404s_for_unknown_batch(client):
    app.dependency_overrides[deps.get_topic_repo] = lambda: _StubTopicRepo(batch=None)

    response = client.get("/topics/batches/unknown/events")

    assert response.status_code == 404


def test_list_topics_filters_by_status_and_subject(client):
    stub_repo = _StubTopicRepo()
    app.dependency_overrides[deps.get_topic_repo] = lambda: stub_repo

    response = client.get("/topics", params={"status": "suggested", "subject": "polity_governance"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert stub_repo.list_calls[-1]["status"] == "suggested"
    assert stub_repo.list_calls[-1]["subject"] == "polity_governance"


def test_get_topic_returns_detail(client):
    app.dependency_overrides[deps.get_topic_repo] = lambda: _StubTopicRepo()

    response = client.get("/topics/topic-1")

    assert response.status_code == 200
    assert response.json()["topic_id"] == "topic-1"


def test_get_topic_404s_for_unknown_topic(client):
    app.dependency_overrides[deps.get_topic_repo] = lambda: _StubTopicRepo(topic=None)

    response = client.get("/topics/unknown")

    assert response.status_code == 404


def test_select_topic_marks_selected_and_starts_researcher(client):
    stub_repo = _StubTopicRepo()
    stub_researcher = _StubResearcher()
    app.dependency_overrides[deps.get_topic_repo] = lambda: stub_repo
    app.dependency_overrides[deps.get_researcher] = lambda: stub_researcher

    response = client.post("/topics/topic-1/select")

    assert response.status_code == 202
    body = response.json()
    assert body["topic_id"] == "topic-1"
    assert "run_id" in body
    assert stub_repo.selected == ["topic-1"]
    assert len(stub_researcher.calls) == 1
    assert stub_researcher.calls[0].topic == _TOPIC_ROW["title"]
    assert stub_researcher.calls[0].audience_tag == "UPSC"
    assert stub_researcher.calls[0].topic_id == "topic-1"


def test_select_topic_404s_for_unknown_topic(client):
    app.dependency_overrides[deps.get_topic_repo] = lambda: _StubTopicRepo(topic=None)
    app.dependency_overrides[deps.get_researcher] = lambda: _StubResearcher()

    response = client.post("/topics/unknown/select")

    assert response.status_code == 404
