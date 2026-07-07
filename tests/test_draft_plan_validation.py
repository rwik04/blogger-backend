import pytest

from agents.strategist.models import DraftedOutlineSection, DraftedPlan
from agents.strategist.nodes.draft_plan import check_business_rules, make_draft_plan_node

_VALID_OUTLINE = [
    DraftedOutlineSection(section_id="intro", heading="Intro", target_keyword="48 teams", order_index=0),
    DraftedOutlineSection(section_id="format", heading="Format", target_keyword="12 groups", order_index=1),
    DraftedOutlineSection(section_id="hosts", heading="Hosts", target_keyword="USA Canada Mexico", order_index=2),
]


def _plan(outline: list[DraftedOutlineSection]) -> DraftedPlan:
    return DraftedPlan(
        primary_keyword="48 teams",
        secondary_keywords=["12 groups"],
        meta_title="Title",
        meta_description="Description",
        slug="slug",
        narrative_angle="Angle.",
        outline=outline,
    )


def test_check_business_rules_passes_valid_plan():
    assert check_business_rules(_plan(_VALID_OUTLINE)) is None


def test_check_business_rules_flags_too_few_sections():
    outline = _VALID_OUTLINE[:2]
    issue = check_business_rules(_plan(outline))
    assert issue is not None
    assert "at least 3" in issue


def test_check_business_rules_flags_majority_missing_target_keyword():
    outline = [
        DraftedOutlineSection(section_id="a", heading="A", target_keyword=None, order_index=0),
        DraftedOutlineSection(section_id="b", heading="B", target_keyword=None, order_index=1),
        DraftedOutlineSection(section_id="c", heading="C", target_keyword="grounded", order_index=2),
    ]
    issue = check_business_rules(_plan(outline))
    assert issue is not None
    assert "missing a target_keyword" in issue


def test_check_business_rules_flags_sentence_length_keyword():
    outline = [
        *_VALID_OUTLINE[:2],
        DraftedOutlineSection(
            section_id="hosts",
            heading="Hosts",
            target_keyword="The tournament will be jointly hosted by the USA, Canada and Mexico",
            order_index=2,
        ),
    ]
    issue = check_business_rules(_plan(outline))
    assert issue is not None
    assert "short search phrases" in issue


def test_check_business_rules_flags_sentence_length_primary_keyword():
    plan = DraftedPlan(
        primary_keyword="The tournament will be jointly hosted by the USA, Canada and Mexico",
        secondary_keywords=["12 groups"],
        meta_title="Title",
        meta_description="Description",
        slug="slug",
        narrative_angle="Angle.",
        outline=_VALID_OUTLINE,
    )
    issue = check_business_rules(plan)
    assert issue is not None
    assert "short search phrases" in issue


class _StubLLMClient:
    """Mimics `LLMClient.reason()` — returns a scripted sequence of
    responses, one per call, so the repair-retry path can be tested without
    a real OpenAI call.
    """

    def __init__(self, responses: list[DraftedPlan]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[dict], type, str | None]] = []

    def reason(self, messages, schema, reasoning_effort=None):
        self.calls.append((messages, schema, reasoning_effort))
        return self._responses.pop(0)


_RESEARCH_BRIEF = {
    "claims": [
        {"id": "c1", "text": "The tournament features 48 teams.", "source_ids": ["s1"], "confidence": "high", "contradicted": False},
    ],
    "sources": [
        {"id": "s1", "url": "https://example.com", "title": "World Cup 2026 format", "domain": "example.com", "retrieved_at": "now"},
    ],
}


async def test_draft_plan_node_retries_once_on_business_rule_failure():
    invalid_plan = _plan(_VALID_OUTLINE[:2])  # only 2 sections -> fails business rule
    valid_plan = _plan(_VALID_OUTLINE)
    stub = _StubLLMClient([invalid_plan, valid_plan])

    node = make_draft_plan_node(stub, reasoning_effort="low")
    result = await node({"topic": "FIFA World Cup 2026", "audience_tag": None, "research_brief": _RESEARCH_BRIEF})

    assert len(stub.calls) == 2
    assert result["drafted_plan"]["outline"] == [s.model_dump() for s in _VALID_OUTLINE]
    assert "_event_summary" in result
    # reasoning_effort is forwarded on every call, including the retry.
    assert all(effort == "low" for _messages, _schema, effort in stub.calls)


async def test_draft_plan_node_raises_after_failed_repair_retry():
    invalid_plan = _plan(_VALID_OUTLINE[:2])
    stub = _StubLLMClient([invalid_plan, invalid_plan])

    node = make_draft_plan_node(stub, reasoning_effort="low")
    with pytest.raises(ValueError, match="business-rule check"):
        await node({"topic": "FIFA World Cup 2026", "audience_tag": None, "research_brief": _RESEARCH_BRIEF})

    assert len(stub.calls) == 2
