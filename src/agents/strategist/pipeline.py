"""Builds the Strategist `CompiledGraph` — a linear pipeline (no iterative
loop, unlike the Researcher): one LLM call, one pure-Python grounding check,
then persistence.

    draft_plan -> grounding_check -> persist_plan
"""

from __future__ import annotations

from agents.strategist.nodes.draft_plan import make_draft_plan_node
from agents.strategist.nodes.grounding_check import make_grounding_check_node
from agents.strategist.nodes.persist import make_persist_plan_node
from db.repositories.strategist_repository import StrategistRepository
from graph.engine import END, CompiledGraph, Graph, NodeFn
from graph.events import EventEmitter, with_events
from llm.client import LLMClient


def build_strategist_graph(
    llm_client: LLMClient,
    repo: StrategistRepository,
    reasoning_effort: str | None = "low",
    emitter: EventEmitter | None = None,
) -> CompiledGraph:
    def wrap(name: str, fn: NodeFn) -> NodeFn:
        return with_events(name, fn, emitter) if emitter is not None else with_events(name, fn)

    graph = Graph()
    graph.add_node("draft_plan", wrap("draft_plan", make_draft_plan_node(llm_client, reasoning_effort)))
    graph.add_node("grounding_check", wrap("grounding_check", make_grounding_check_node()))
    graph.add_node("persist_plan", wrap("persist_plan", make_persist_plan_node(repo)))

    graph.set_entry("draft_plan")
    graph.add_edge("draft_plan", "grounding_check")
    graph.add_edge("grounding_check", "persist_plan")
    graph.add_edge("persist_plan", END)

    return graph.compile()
