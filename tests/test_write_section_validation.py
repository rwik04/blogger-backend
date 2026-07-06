import pytest

from agents.writer.models import DraftedSection
from agents.writer.nodes.write_section import make_write_section_node

_LONG_BODY = " ".join(["word"] * 60)  # >= 50 words, avoids the length-retry path
_SHORT_BODY = "Too short."  # < 50 words, triggers the length-retry path

_OUTLINE = [
    {"section_id": "intro", "heading": "Intro", "target_keyword": "kw1", "grounded": True, "order_index": 0},
    {"section_id": "body", "heading": "Body", "target_keyword": "kw2", "grounded": True, "order_index": 1},
    {"section_id": "conclusion", "heading": "Conclusion", "target_keyword": None, "grounded": False, "order_index": 2},
]

_CLAIMS = [
    {"id": "claim-1", "text": "The sky is blue.", "source_ids": ["s1"], "confidence": "high", "contradicted": False},
    {"id": "claim-2", "text": "Water boils at 100C.", "source_ids": ["s2"], "confidence": "high", "contradicted": False},
]


def _base_state(outline=None, **overrides):
    state = {
        "run_id": "run-1",
        "topic": "Test Topic",
        "audience_tag": None,
        "research_brief": {"claims": _CLAIMS},
        "outline": outline if outline is not None else _OUTLINE,
        "current_section_index": 0,
        "draft_so_far": "",
        "sections": [],
        "needs_more_research": [],
        "consecutive_section_failures": 0,
    }
    state.update(overrides)
    return state


class _StubLLMClient:
    """Mimics `LLMClient.reason()` — returns a scripted sequence of
    responses (or raises a scripted exception), one per call.
    """

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[dict], type, str | None]] = []

    def reason(self, messages, schema, reasoning_effort=None):
        self.calls.append((messages, schema, reasoning_effort))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _section(body_markdown, claim_ids, unsupported_gaps, tone_notes="polished") -> DraftedSection:
    return DraftedSection(
        body_markdown=body_markdown, claim_ids=claim_ids, unsupported_gaps=unsupported_gaps, tone_notes=tone_notes
    )


async def test_gap_retry_stops_after_two_attempts_and_logs_unresolved_gap():
    responses = [
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),  # still has a gap after 2 retries -> accepted as-is
    ]
    stub = _StubLLMClient(responses)
    node = make_write_section_node(stub, reasoning_effort="low")

    result = await node(_base_state())

    assert len(stub.calls) == 3  # initial + 2 gap retries, no more
    section_result = result["sections"][0]
    assert section_result["retries_used"] == 2
    assert section_result["unsupported_gaps"] == ["gap A"]
    assert any("gap A" in gap for gap in result["needs_more_research"])


async def test_length_retry_is_a_separate_budget_from_gap_retry():
    responses = [
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),  # has a gap -> triggers gap retry
        _section(_SHORT_BODY, ["claim-1"], []),  # gap resolved, but now too short -> triggers length retry
        _section(_LONG_BODY, ["claim-1"], []),  # resolved
    ]
    stub = _StubLLMClient(responses)
    node = make_write_section_node(stub, reasoning_effort="low")

    result = await node(_base_state())

    assert len(stub.calls) == 3
    section_result = result["sections"][0]
    assert section_result["retries_used"] == 2  # 1 gap retry + 1 length retry
    assert section_result["unsupported_gaps"] == []
    assert result["needs_more_research"] == []


async def test_claim_ids_are_filtered_to_known_brief_claims():
    responses = [_section(_LONG_BODY, ["claim-1", "claim-999", "not-a-claim"], [])]
    stub = _StubLLMClient(responses)
    node = make_write_section_node(stub, reasoning_effort="low")

    result = await node(_base_state())

    assert result["sections"][0]["claim_ids"] == ["claim-1"]


async def test_single_isolated_section_failure_does_not_raise_and_is_logged():
    stub = _StubLLMClient([RuntimeError("boom")])
    node = make_write_section_node(stub, reasoning_effort="low")

    result = await node(_base_state())

    assert result["consecutive_section_failures"] == 1
    assert any("failed to generate" in note for note in result["needs_more_research"])
    assert "sections" not in result  # no SectionResult appended for a failed section


async def test_two_consecutive_section_failures_raises():
    stub = _StubLLMClient([RuntimeError("boom"), RuntimeError("boom again")])
    node = make_write_section_node(stub, reasoning_effort="low")

    first = await node(_base_state())
    assert first["consecutive_section_failures"] == 1

    second_state = _base_state(current_section_index=1, consecutive_section_failures=1)
    with pytest.raises(RuntimeError, match="consecutive sections failed"):
        await node(second_state)


async def test_single_section_outline_with_gap_populates_needs_more_research():
    single_outline = [_OUTLINE[0]]
    responses = [
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),
    ]
    stub = _StubLLMClient(responses)
    node = make_write_section_node(stub, reasoning_effort="low")

    result = await node(_base_state(outline=single_outline))

    assert len(result["sections"]) == 1
    assert any("gap A" in gap for gap in result["needs_more_research"])
