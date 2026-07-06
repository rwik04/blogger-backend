from agents.researcher.nodes.write_report import (
    _assign_citation_numbers,
    _build_sources_section,
    _claim_citation_marker,
)


def _source(id_: str, title: str = "T", url: str = "https://example.com", domain: str = "example.com"):
    return {"id": id_, "title": title, "url": url, "domain": domain, "retrieved_at": "now"}


def test_citation_numbers_follow_source_list_order():
    sources = [_source("a"), _source("b"), _source("c")]
    numbers = _assign_citation_numbers(sources)
    assert numbers == {"a": 1, "b": 2, "c": 3}


def test_claim_citation_marker_dedupes_and_sorts():
    numbers = {"a": 1, "b": 2, "c": 3}
    claim = {"source_ids": ["c", "a", "a", "b"]}
    assert _claim_citation_marker(claim, numbers) == "[1][2][3]"


def test_claim_citation_marker_ignores_unknown_source_ids():
    numbers = {"a": 1}
    claim = {"source_ids": ["a", "does-not-exist"]}
    assert _claim_citation_marker(claim, numbers) == "[1]"


def test_sources_section_lists_in_citation_number_order():
    sources = [_source("a", title="A", url="https://a.com"), _source("b", title="B", url="https://b.com")]
    numbers = {"a": 1, "b": 2}
    section = _build_sources_section(sources, numbers)
    lines = section.splitlines()
    assert lines[0] == "## Sources"
    assert lines[1] == "1. [A](https://a.com) — example.com"
    assert lines[2] == "2. [B](https://b.com) — example.com"
