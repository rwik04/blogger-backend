"""trim_by_relevance: no-op passthrough when `max_output` isn't set (today's
keep-everything behavior for manual/directed generation); keeps only the top
`max_output` candidates by `relevance_score`, highest first, when it is set
(used by the daily autonomous cron to trim a wide net down to the best few).
"""

from __future__ import annotations

import asyncio

from agents.topic_generator.nodes.trim_by_relevance import make_trim_by_relevance_node

_CANDIDATES = [
    {"candidate_id": "a", "title": "A", "relevance_score": 40},
    {"candidate_id": "b", "title": "B", "relevance_score": 90},
    {"candidate_id": "c", "title": "C", "relevance_score": 65},
    {"candidate_id": "d", "title": "D", "relevance_score": 10},
]


def test_no_max_output_keeps_all_candidates():
    node = make_trim_by_relevance_node()

    result = asyncio.run(node({"classified_candidates": _CANDIDATES, "max_output": None}))

    assert result["classified_candidates"] == _CANDIDATES


def test_max_output_keeps_top_n_by_relevance_score_descending():
    node = make_trim_by_relevance_node()

    result = asyncio.run(node({"classified_candidates": _CANDIDATES, "max_output": 2}))

    kept = result["classified_candidates"]
    assert [c["candidate_id"] for c in kept] == ["b", "c"]


def test_max_output_larger_than_candidate_count_is_a_no_op():
    node = make_trim_by_relevance_node()

    result = asyncio.run(node({"classified_candidates": _CANDIDATES, "max_output": 100}))

    assert len(result["classified_candidates"]) == len(_CANDIDATES)


def test_missing_max_output_key_defaults_to_keeping_all():
    node = make_trim_by_relevance_node()

    result = asyncio.run(node({"classified_candidates": _CANDIDATES}))

    assert len(result["classified_candidates"]) == len(_CANDIDATES)
