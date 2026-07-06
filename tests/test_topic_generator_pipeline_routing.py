"""End-to-end pipeline routing: the diversity-nudge retry-once loop through
`extract_candidates -> dedup_filter` — all-duplicates on the first attempt
loops back once, still-all-duplicates on the second attempt proceeds anyway
rather than looping forever or silently returning empty (TOPIC_GENERATOR.md
§8).
"""

from __future__ import annotations

import asyncio

from agents.topic_generator.models import (
    ClassifiedCandidate,
    ClassifiedCandidateSet,
    ExtractedCandidate,
    ExtractedCandidateSet,
    GsPaper,
    UpscSubject,
)
from agents.topic_generator.pipeline import build_topic_generator_graph


class _StubLLMClient:
    """Extraction always returns the same single candidate title (so the
    dedup stub can keep flagging it as a duplicate); classification always
    tags it identically. Counts extraction calls to prove the retry-once
    (not retry-forever) behavior.
    """

    def __init__(self):
        self.extract_calls = 0

    def reason(self, messages, schema, reasoning_effort=None):
        if schema is ExtractedCandidateSet:
            self.extract_calls += 1
            return ExtractedCandidateSet(
                candidates=[
                    ExtractedCandidate(
                        title="Always duplicate topic",
                        one_line_summary="Same story every time.",
                        trigger_source_url=None,
                    )
                ]
            )
        if schema is ClassifiedCandidateSet:
            return ClassifiedCandidateSet(
                classifications=[
                    ClassifiedCandidate(
                        subject=UpscSubject.MISCELLANEOUS_CURRENT_AFFAIRS,
                        gs_papers=[GsPaper.PRELIMS_ONLY],
                        why_this_topic="why",
                        current_relevance="relevance",
                    )
                ]
            )
        raise AssertionError(f"unexpected schema requested: {schema}")


class _AlwaysDuplicateTopicRepo:
    """Every candidate title looks like an obvious duplicate of prior work."""

    def __init__(self):
        self.saved_candidates: list[dict] = []

    def find_similar_topics(self, title, limit=5):
        return [{"id": "existing", "title": title, "similarity_score": 0.9}]

    def save_candidates(self, batch_id, candidates):
        self.saved_candidates.extend(candidates)


class _NoOpMCPClient:
    async def call_tool(self, name, arguments):
        raise AssertionError("search_candidates should not run without queries staged")


def test_all_duplicates_retries_extraction_once_then_proceeds():
    llm_client = _StubLLMClient()
    repo = _AlwaysDuplicateTopicRepo()
    graph = build_topic_generator_graph(llm_client, _NoOpMCPClient(), repo, reasoning_effort="low")

    initial_state = {
        "run_id": "batch-1",
        "batch_id": "batch-1",
        "mode": "autonomous",
        "user_instruction": None,
        "count": 8,
        "auto_approve": False,
        # Bypass build_queries/search_candidates for this routing-focused test:
        # seed extract_candidates' input directly.
        "search_rounds": [{"query": "q", "hits": [{"title": "t", "url": "https://example.com", "snippet": "s"}]}],
    }

    final_state = asyncio.run(_run_from(graph, initial_state, "extract_candidates"))

    # Retried exactly once (initial attempt + one nudge), never looped a third time.
    assert llm_client.extract_calls == 2
    assert final_state["dedup_results"][0]["dedup_status"] == "similar_to_existing"
    assert len(final_state["classified_candidates"]) == 1
    assert len(repo.saved_candidates) == 1


async def _run_from(graph, initial_state: dict, start_node: str) -> dict:
    """Runs the compiled graph starting from an arbitrary node — used here to
    skip `build_queries`/`search_candidates` and drive the routing logic
    directly against pre-seeded `search_rounds`.
    """
    state = dict(initial_state)
    current = start_node
    graph_internal = graph._graph  # noqa: SLF001 - test-only introspection

    from graph.engine import END

    while current is not None and current != END:
        fn = graph_internal._nodes[current]
        update = await fn(state)
        if update:
            state.update(update)
        if current in graph_internal._conditional_edges:
            current = graph_internal._conditional_edges[current](state)
        elif current in graph_internal._edges:
            current = graph_internal._edges[current]
        else:
            current = None
    return state
