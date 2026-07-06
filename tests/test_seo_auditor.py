from agents.finisher.nodes.audit_seo import (
    check_headings,
    check_meta_description,
    compute_keyword_density,
    suggest_internal_links,
)


def test_keyword_density_below_within_and_above_thresholds():
    # 200 words total: "rare" appears 0 times (0%), "common" 4 times (2%),
    # "everywhere" 10 times (5%).
    words = ["filler"] * 186 + ["common"] * 4 + ["everywhere"] * 10
    body_text = " ".join(words)

    density = compute_keyword_density(body_text, ["rare", "common", "everywhere"])

    assert density["rare"] == 0.0
    assert 0.005 < density["common"] < 0.03
    assert density["everywhere"] > 0.03


def test_meta_description_length():
    assert check_meta_description("x" * 140) is True
    assert check_meta_description("too short") is False
    assert check_meta_description("x" * 200) is False


def test_check_headings_flags_stray_headers_but_not_plain_text():
    sections = [
        {"section_id": "intro", "body_markdown": "# A stray H1\n\nSome body text."},
        {"section_id": "logistics", "body_markdown": "### A stray H3\n\nMore body text."},
        {"section_id": "conclusion", "body_markdown": "Just plain body text, no headers."},
    ]

    issues = check_headings(sections, final_title="The Real Title")

    assert len(issues) == 2
    assert any("H1" in issue and "intro" in issue for issue in issues)
    assert any("H3" in issue and "logistics" in issue for issue in issues)


def test_suggest_internal_links_pairs_sections_with_shared_keyword_words():
    outline = [
        {"section_id": "s1", "target_keyword": "world cup host cities"},
        {"section_id": "s2", "target_keyword": "host cities stadiums"},
        {"section_id": "s3", "target_keyword": "ticket prices"},
    ]

    suggestions = suggest_internal_links(outline)

    assert len(suggestions) == 1
    assert {suggestions[0]["from_section"], suggestions[0]["to_section"]} == {"s1", "s2"}


def test_suggest_internal_links_ignores_sections_without_target_keyword():
    outline = [
        {"section_id": "s1", "target_keyword": "world cup host cities"},
        {"section_id": "s2", "target_keyword": None},
    ]

    assert suggest_internal_links(outline) == []
