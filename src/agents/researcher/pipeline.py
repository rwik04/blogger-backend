"""Builds the Researcher `CompiledGraph` — wires the nodes from
`agents.researcher.nodes` onto `graph.engine.Graph`, with the iterative
search -> compact -> reflect loop as the central structure.

Named `pipeline.py`, not `graph.py`, deliberately: a same-named sibling of
the top-level `graph` package (`src/graph/`) breaks `from graph.engine import
...` when this file is ever run directly as a script rather than via
`python -m` — running a script inserts its own directory at the front of
`sys.path`, which would shadow the real `graph` package with this file.

See the flow diagram in the plan for the full picture; in short:

    plan_queries -> search_round (fan-out) -> filter_rank -> selective_scrape
        -> compact_round -> reflect_coverage --(continue)--> search_round
                                              --(finalize)--> finalize_brief
                                                                   |
                                                    (>=3 sources)  |  (<3 sources)
                                                     write_report      fail_step
                                                          |
                                                     persist_brief
"""

from __future__ import annotations

from typing import Any

from agents.researcher.nodes.compact_round import make_compact_round_node
from agents.researcher.nodes.filter_rank import make_filter_rank_node
from agents.researcher.nodes.finalize import make_fail_step_node, make_finalize_brief_node, route_after_finalize
from agents.researcher.nodes.persist import make_persist_brief_node
from agents.researcher.nodes.plan_queries import make_plan_queries_node
from agents.researcher.nodes.reflect_coverage import make_reflect_coverage_node
from agents.researcher.nodes.search import make_search_subquery_fn, make_selective_scrape_node
from agents.researcher.nodes.write_report import make_write_report_node
from db.repositories.research_repository import ResearchRepository
from graph.engine import END, CompiledGraph, Graph, build_fanout_node
from graph.events import EventEmitter, with_events
from llm.client import LLMClient
from mcpclient.client import MCPClient

_SEARCH_CONCURRENCY = 3


def route_after_reflect(state: dict[str, Any]) -> str:
    """The loop-back edge. Mutates `state` in place to stage the next round's
    inputs before returning to `search_round` — see `Graph.add_conditional_edge`.
    """
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)
    already_asked = set(state.get("sub_queries_asked", []))
    proposed = state.get("sub_queries_this_round") or []
    next_queries = [q for q in proposed if q not in already_asked]

    can_continue = (
        state.get("reflect_decision") == "continue"
        and iteration + 1 < max_iterations
        and bool(next_queries)
    )
    if not can_continue:
        return "finalize_brief"

    state["iteration"] = iteration + 1
    state["sub_queries_this_round"] = next_queries
    state["sub_queries_asked"] = state.get("sub_queries_asked", []) + next_queries
    return "search_round"


def build_researcher_graph(
    llm_client: LLMClient,
    mcp_client: MCPClient,
    repo: ResearchRepository,
    emitter: EventEmitter | None = None,
) -> CompiledGraph:
    def wrap(name: str, fn):
        return with_events(name, fn, emitter) if emitter is not None else with_events(name, fn)

    graph = Graph()

    graph.add_node("plan_queries", wrap("plan_queries", make_plan_queries_node(llm_client)))
    search_round_fn = build_fanout_node(
        "search_round",
        make_search_subquery_fn(mcp_client),
        items_key="sub_queries_this_round",
        result_key="round_search_results",
        max_concurrency=_SEARCH_CONCURRENCY,
    )
    graph.add_node("search_round", wrap("search_round", search_round_fn))
    graph.add_node("filter_rank", wrap("filter_rank", make_filter_rank_node()))
    graph.add_node("selective_scrape", wrap("selective_scrape", make_selective_scrape_node(mcp_client)))
    graph.add_node("compact_round", wrap("compact_round", make_compact_round_node(llm_client)))
    graph.add_node("reflect_coverage", wrap("reflect_coverage", make_reflect_coverage_node(llm_client)))
    graph.add_node("finalize_brief", wrap("finalize_brief", make_finalize_brief_node()))
    graph.add_node("fail_step", wrap("fail_step", make_fail_step_node()))
    graph.add_node("write_report", wrap("write_report", make_write_report_node(llm_client)))
    graph.add_node("persist_brief", wrap("persist_brief", make_persist_brief_node(repo)))

    graph.set_entry("plan_queries")
    graph.add_edge("plan_queries", "search_round")
    graph.add_edge("search_round", "filter_rank")
    graph.add_edge("filter_rank", "selective_scrape")
    graph.add_edge("selective_scrape", "compact_round")
    graph.add_edge("compact_round", "reflect_coverage")
    graph.add_conditional_edge("reflect_coverage", route_after_reflect)
    graph.add_conditional_edge("finalize_brief", route_after_finalize)
    graph.add_edge("write_report", "persist_brief")
    graph.add_edge("persist_brief", END)
    graph.add_edge("fail_step", END)

    return graph.compile()
