"""Builds the Topic Generator `CompiledGraph` — wires the nodes from
`agents.topic_generator.nodes` onto `graph.engine.Graph`.

Named `pipeline.py`, not `graph.py`, for the same reason as the Researcher's
(see `agents/researcher/pipeline.py`): avoids shadowing the top-level
`graph` package if this module is ever run as a script directly.

    build_queries -> search_candidates (fan-out) -> extract_candidates -> dedup_filter
        --(all duplicates, first attempt)--> extract_candidates
        --(otherwise)--> classify -> trim_by_relevance -> persist
"""

from __future__ import annotations

from typing import Any

from agents.topic_generator.nodes.build_queries import make_build_queries_node
from agents.topic_generator.nodes.classify import make_classify_node
from agents.topic_generator.nodes.dedup_filter import make_dedup_filter_node, route_after_dedup
from agents.topic_generator.nodes.extract_candidates import make_extract_candidates_node
from agents.topic_generator.nodes.persist import make_persist_node
from agents.topic_generator.nodes.search_candidates import (
    make_search_query_fn,
    summarize_search_candidates,
)
from agents.topic_generator.nodes.trim_by_relevance import make_trim_by_relevance_node
from db.repositories.topic_repository import TopicRepository
from graph.engine import END, CompiledGraph, Graph, build_fanout_node
from graph.events import EventEmitter, with_events
from llm.client import LLMClient
from mcpclient.client import MCPClient

_SEARCH_CONCURRENCY = 3


def build_topic_generator_graph(
    llm_client: LLMClient,
    mcp_client: MCPClient,
    repo: TopicRepository,
    reasoning_effort: str | None = "low",
    emitter: EventEmitter | None = None,
) -> CompiledGraph:
    def wrap(name: str, fn):
        return with_events(name, fn, emitter) if emitter is not None else with_events(name, fn)

    def with_summary(fn, summary_fn):
        async def wrapped(state: dict[str, Any]) -> dict[str, Any] | None:
            result = await fn(state)
            if result is not None:
                summary = summary_fn(state, result)
                if summary:
                    result = {**result, "_event_summary": summary}
            return result

        return wrapped

    graph = Graph()

    graph.add_node("build_queries", wrap("build_queries", make_build_queries_node(llm_client)))

    search_candidates_fn = build_fanout_node(
        "search_candidates",
        make_search_query_fn(mcp_client),
        items_key="queries",
        result_key="search_rounds",
        max_concurrency=_SEARCH_CONCURRENCY,
    )
    graph.add_node(
        "search_candidates",
        wrap("search_candidates", with_summary(search_candidates_fn, summarize_search_candidates)),
    )

    graph.add_node(
        "extract_candidates",
        wrap("extract_candidates", make_extract_candidates_node(llm_client, reasoning_effort)),
    )
    graph.add_node(
        "dedup_filter", wrap("dedup_filter", make_dedup_filter_node(llm_client, repo, reasoning_effort))
    )
    graph.add_node("classify", wrap("classify", make_classify_node(llm_client, reasoning_effort)))
    graph.add_node("trim_by_relevance", wrap("trim_by_relevance", make_trim_by_relevance_node()))
    graph.add_node("persist", wrap("persist", make_persist_node(repo)))

    graph.set_entry("build_queries")
    graph.add_edge("build_queries", "search_candidates")
    graph.add_edge("search_candidates", "extract_candidates")
    graph.add_edge("extract_candidates", "dedup_filter")
    graph.add_conditional_edge("dedup_filter", route_after_dedup)
    graph.add_edge("classify", "trim_by_relevance")
    graph.add_edge("trim_by_relevance", "persist")
    graph.add_edge("persist", END)

    return graph.compile()
