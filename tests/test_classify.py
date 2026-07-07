"""classify: one batched LLM call, classifications zipped positionally onto
the input candidates. A length mismatch (fewer classifications than
candidates) falls back to the miscellaneous catch-all for the unmatched
candidates rather than raising (TOPIC_GENERATOR.md §7).
"""

from __future__ import annotations

import asyncio

from agents.topic_generator.models import ClassifiedCandidate, ClassifiedCandidateSet, GsPaper, UpscSubject
from agents.topic_generator.nodes.classify import make_classify_node

_CANDIDATES = [
    {
        "candidate_id": "c1",
        "title": "Supreme Court ruling on free speech",
        "one_line_summary": "A summary.",
        "trigger_source_url": None,
        "dedup_status": "new",
        "similarity_score": None,
    },
    {
        "candidate_id": "c2",
        "title": "A story that doesn't fit any subject well",
        "one_line_summary": "Another summary.",
        "trigger_source_url": None,
        "dedup_status": "new",
        "similarity_score": None,
    },
]


class _StubLLMClient:
    def __init__(self, classifications: list[ClassifiedCandidate]):
        self._classifications = classifications

    def reason(self, messages, schema, reasoning_effort=None):
        return ClassifiedCandidateSet(classifications=self._classifications)


def test_classifications_zipped_positionally_onto_candidates():
    classifications = [
        ClassifiedCandidate(
            subject=UpscSubject.POLITY_GOVERNANCE,
            gs_papers=[GsPaper.GS2],
            why_this_topic="Polity relevance.",
            current_relevance="Recent ruling.",
            relevance_score=85,
        ),
        ClassifiedCandidate(
            subject=UpscSubject.MISCELLANEOUS_CURRENT_AFFAIRS,
            gs_papers=[GsPaper.PRELIMS_ONLY],
            why_this_topic="Broad awareness.",
            current_relevance="Recent event.",
            relevance_score=35,
        ),
    ]
    node = make_classify_node(_StubLLMClient(classifications))

    result = asyncio.run(node({"dedup_results": _CANDIDATES}))

    merged = result["classified_candidates"]
    assert merged[0]["candidate_id"] == "c1"
    assert merged[0]["subject"] == UpscSubject.POLITY_GOVERNANCE.value
    assert merged[0]["relevance_score"] == 85
    assert merged[1]["candidate_id"] == "c2"
    assert merged[1]["subject"] == UpscSubject.MISCELLANEOUS_CURRENT_AFFAIRS.value
    assert merged[1]["relevance_score"] == 35


def test_bad_fit_candidate_falls_back_to_miscellaneous_without_raising():
    classifications = [
        ClassifiedCandidate(
            subject=UpscSubject.MISCELLANEOUS_CURRENT_AFFAIRS,
            gs_papers=[GsPaper.PRELIMS_ONLY],
            why_this_topic="Doesn't fit cleanly anywhere.",
            current_relevance="Still current.",
            relevance_score=30,
        )
    ]
    node = make_classify_node(_StubLLMClient(classifications))

    result = asyncio.run(node({"dedup_results": _CANDIDATES[:1]}))

    assert result["classified_candidates"][0]["subject"] == UpscSubject.MISCELLANEOUS_CURRENT_AFFAIRS.value


def test_length_mismatch_pads_unmatched_candidates_with_fallback():
    # Only one classification returned for two candidates.
    classifications = [
        ClassifiedCandidate(
            subject=UpscSubject.POLITY_GOVERNANCE,
            gs_papers=[GsPaper.GS2],
            why_this_topic="Polity relevance.",
            current_relevance="Recent ruling.",
            relevance_score=85,
        )
    ]
    node = make_classify_node(_StubLLMClient(classifications))

    result = asyncio.run(node({"dedup_results": _CANDIDATES}))

    merged = result["classified_candidates"]
    assert len(merged) == 2
    assert merged[0]["subject"] == UpscSubject.POLITY_GOVERNANCE.value
    assert merged[0]["relevance_score"] == 85
    assert merged[1]["subject"] == UpscSubject.MISCELLANEOUS_CURRENT_AFFAIRS.value
    assert merged[1]["gs_papers"] == [GsPaper.PRELIMS_ONLY.value]
    assert merged[1]["relevance_score"] == 40
