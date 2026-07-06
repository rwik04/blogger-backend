"""dedup_filter: pure decision-logic tests against a stubbed
`TopicRepository.find_similar_topics` returning canned scores — no live
DB/pg_trgm needed. TOPIC_GENERATOR.md §10's three fixed bands: obvious
duplicate (>=0.4, no LLM call needed), ambiguous (0.25-0.4, triggers the LLM
tiebreak), and clearly unrelated (<0.25).
"""

from __future__ import annotations

import asyncio

from agents.topic_generator.models import DedupStatus, DedupTiebreakDecision
from agents.topic_generator.nodes.dedup_filter import make_dedup_filter_node, route_after_dedup

_CANDIDATE = {
    "candidate_id": "c1",
    "title": "New topic title",
    "one_line_summary": "A short summary.",
    "trigger_source_url": None,
}


class _StubRepo:
    def __init__(self, matches: list[dict]):
        self._matches = matches

    def find_similar_topics(self, title, limit=5):
        return self._matches


class _TiebreakLLMClient:
    def __init__(self, same_underlying_story: bool):
        self._same_underlying_story = same_underlying_story
        self.called = False

    def reason(self, messages, schema, reasoning_effort=None):
        self.called = True
        return DedupTiebreakDecision(same_underlying_story=self._same_underlying_story, reasoning="because")


class _UnusedLLMClient:
    def reason(self, messages, schema, reasoning_effort=None):
        raise AssertionError("LLM tiebreak must not be called outside the ambiguous band")


def test_obvious_duplicate_skips_llm_tiebreak():
    repo = _StubRepo([{"id": "existing-1", "title": "Existing topic", "similarity_score": 0.55}])
    node = make_dedup_filter_node(_UnusedLLMClient(), repo)

    result = asyncio.run(node({"extracted_candidates": [_CANDIDATE]}))

    assert result["dedup_results"][0]["dedup_status"] == DedupStatus.SIMILAR_TO_EXISTING.value
    assert result["dedup_results"][0]["similarity_score"] == 0.55


def test_ambiguous_band_triggers_llm_tiebreak_same_story():
    repo = _StubRepo([{"id": "existing-1", "title": "Existing topic", "similarity_score": 0.3}])
    llm_client = _TiebreakLLMClient(same_underlying_story=True)
    node = make_dedup_filter_node(llm_client, repo)

    result = asyncio.run(node({"extracted_candidates": [_CANDIDATE]}))

    assert llm_client.called is True
    assert result["dedup_results"][0]["dedup_status"] == DedupStatus.SIMILAR_TO_EXISTING.value


def test_ambiguous_band_triggers_llm_tiebreak_different_story():
    repo = _StubRepo([{"id": "existing-1", "title": "Existing topic", "similarity_score": 0.3}])
    llm_client = _TiebreakLLMClient(same_underlying_story=False)
    node = make_dedup_filter_node(llm_client, repo)

    result = asyncio.run(node({"extracted_candidates": [_CANDIDATE]}))

    assert llm_client.called is True
    assert result["dedup_results"][0]["dedup_status"] == DedupStatus.NEW.value


def test_clearly_unrelated_is_new_without_llm_call():
    repo = _StubRepo([{"id": "existing-1", "title": "Existing topic", "similarity_score": 0.1}])
    node = make_dedup_filter_node(_UnusedLLMClient(), repo)

    result = asyncio.run(node({"extracted_candidates": [_CANDIDATE]}))

    assert result["dedup_results"][0]["dedup_status"] == DedupStatus.NEW.value


def test_no_matches_at_all_is_new():
    repo = _StubRepo([])
    node = make_dedup_filter_node(_UnusedLLMClient(), repo)

    result = asyncio.run(node({"extracted_candidates": [_CANDIDATE]}))

    assert result["dedup_results"][0]["dedup_status"] == DedupStatus.NEW.value
    assert result["dedup_results"][0]["similarity_score"] is None


def test_route_after_dedup_all_duplicates_first_attempt_loops_back():
    state = {
        "dedup_results": [{**_CANDIDATE, "dedup_status": DedupStatus.SIMILAR_TO_EXISTING.value}],
        "diversity_nudge_attempted": False,
    }

    next_node = route_after_dedup(state)

    assert next_node == "extract_candidates"
    assert state["diversity_nudge_attempted"] is True
    assert state["diversity_nudge_titles"] == [_CANDIDATE["title"]]


def test_route_after_dedup_all_duplicates_second_attempt_proceeds_anyway():
    state = {
        "dedup_results": [{**_CANDIDATE, "dedup_status": DedupStatus.SIMILAR_TO_EXISTING.value}],
        "diversity_nudge_attempted": True,
    }

    assert route_after_dedup(state) == "classify"


def test_route_after_dedup_mixed_results_proceeds_to_classify():
    state = {
        "dedup_results": [
            {**_CANDIDATE, "dedup_status": DedupStatus.SIMILAR_TO_EXISTING.value},
            {**_CANDIDATE, "candidate_id": "c2", "dedup_status": DedupStatus.NEW.value},
        ],
        "diversity_nudge_attempted": False,
    }

    assert route_after_dedup(state) == "classify"
