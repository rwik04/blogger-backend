"""build_queries: autonomous mode is fully deterministic (no LLM call, one
query per `UpscSubject`); directed mode requires a `user_instruction` —
enforced by `TopicGeneratorInput`'s validator before any search happens.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from agents.topic_generator.models import TopicGeneratorInput, TopicGeneratorMode, UpscSubject
from agents.topic_generator.nodes.build_queries import _SUBJECT_QUERY_HINTS, make_build_queries_node


class _UnusedLLMClient:
    def reason(self, messages, schema, reasoning_effort=None):
        raise AssertionError("Autonomous mode must not call the LLM")


class _StubLLMClient:
    def __init__(self, queries: list[str]):
        self._queries = queries
        self.called = False

    def reason(self, messages, schema, reasoning_effort=None):
        self.called = True
        from agents.topic_generator.models import ExpandedQueries

        return ExpandedQueries(queries=self._queries)


def test_autonomous_mode_produces_one_query_per_subject():
    node = make_build_queries_node(_UnusedLLMClient())

    result = asyncio.run(node({"mode": TopicGeneratorMode.AUTONOMOUS.value}))

    assert len(result["queries"]) == len(list(UpscSubject))
    assert len(_SUBJECT_QUERY_HINTS) == len(list(UpscSubject))


def test_directed_mode_expands_instruction_via_one_llm_call():
    llm_client = _StubLLMClient(["query one", "query two"])
    node = make_build_queries_node(llm_client)

    result = asyncio.run(
        node({"mode": TopicGeneratorMode.DIRECTED.value, "user_instruction": "Recent SC rulings"})
    )

    assert llm_client.called is True
    assert result["queries"] == ["query one", "query two"]


def test_directed_mode_without_instruction_fails_validation_before_search():
    with pytest.raises(ValidationError):
        TopicGeneratorInput(mode=TopicGeneratorMode.DIRECTED, user_instruction=None)

    with pytest.raises(ValidationError):
        TopicGeneratorInput(mode=TopicGeneratorMode.DIRECTED, user_instruction="   ")
