import logging

from agents.strategist.nodes.grounding_check import (
    build_grounding_haystack,
    check_outline_grounding,
    is_grounded,
)

_CLAIMS = [
    {"text": "The tournament will feature 48 teams across 12 groups.", "confidence": "high"},
    {"text": "Matches are scheduled across the United States, Canada, and Mexico.", "confidence": "high"},
]
_SOURCES = [
    {"title": "FIFA World Cup 2026 host cities and stadiums", "domain": "fifa.com"},
]


def _section(section_id: str, target_keyword: str | None, order_index: int = 0):
    return {
        "section_id": section_id,
        "heading": "Heading",
        "target_keyword": target_keyword,
        "order_index": order_index,
    }


def test_is_grounded_verbatim_match():
    haystack = build_grounding_haystack(_CLAIMS, _SOURCES)
    assert is_grounded("48 teams", haystack) is True


def test_is_grounded_near_match_via_significant_words():
    haystack = build_grounding_haystack(_CLAIMS, _SOURCES)
    # Words appear individually ("host", "cities") even though this exact
    # phrase isn't a substring of any single claim/title.
    assert is_grounded("host cities 2026", haystack) is True


def test_is_grounded_false_when_absent():
    haystack = build_grounding_haystack(_CLAIMS, _SOURCES)
    assert is_grounded("underwater basket weaving", haystack) is False


def test_check_outline_grounding_sets_grounded_per_section():
    outline = [
        _section("introduction", "48 teams", order_index=0),
        _section("logistics", "underwater basket weaving", order_index=1),
        _section("conclusion", None, order_index=2),
    ]

    result = check_outline_grounding(outline, _CLAIMS, _SOURCES)

    by_id = {s["section_id"]: s for s in result}
    assert by_id["introduction"]["grounded"] is True
    assert by_id["logistics"]["grounded"] is False
    assert by_id["conclusion"]["grounded"] is False
    # Original outline dicts aren't mutated in place.
    assert "grounded" not in outline[0]


def test_check_outline_grounding_warns_on_duplicate_target_keyword(caplog):
    outline = [
        _section("intro", "48 teams", order_index=0),
        _section("recap", "48 teams", order_index=1),
    ]

    with caplog.at_level(logging.WARNING):
        check_outline_grounding(outline, _CLAIMS, _SOURCES)

    assert any("share the same target_keyword" in record.message for record in caplog.records)
