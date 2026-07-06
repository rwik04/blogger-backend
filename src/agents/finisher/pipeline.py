"""Builds the Finisher `CompiledGraph` — linear aside from one quiz on/off
branch. FINISHER.md's quiz "retry" mechanism is over-generation plus
drop-on-failure rather than iterative repair, so no loop is needed here,
unlike the Writer's per-section loop:

    audit_seo --(include_quiz)--> generate_candidate_questions -> validate_questions
        -> assemble_questions -> plan_media -> persist_finisher -> END
    audit_seo --(not include_quiz)--> plan_media -> persist_finisher -> END
"""

from __future__ import annotations

from typing import Any

from agents.finisher.nodes.assemble_questions import make_assemble_questions_node
from agents.finisher.nodes.audit_seo import make_audit_seo_node
from agents.finisher.nodes.generate_candidate_questions import make_generate_candidate_questions_node
from agents.finisher.nodes.persist import make_persist_finisher_node
from agents.finisher.nodes.plan_media import make_plan_media_node
from agents.finisher.nodes.validate_questions import make_validate_questions_node
from db.repositories.finisher_repository import FinisherRepository
from graph.engine import END, CompiledGraph, Graph, NodeFn
from graph.events import EventEmitter, with_events
from llm.client import LLMClient


def _route_after_audit(state: dict[str, Any]) -> str:
    return "generate_candidate_questions" if state.get("include_quiz", True) else "plan_media"


def build_finisher_graph(
    llm_client: LLMClient,
    repo: FinisherRepository,
    reasoning_effort: str | None = "medium",
    emitter: EventEmitter | None = None,
) -> CompiledGraph:
    def wrap(name: str, fn: NodeFn) -> NodeFn:
        return with_events(name, fn, emitter) if emitter is not None else with_events(name, fn)

    graph = Graph()
    graph.add_node("audit_seo", wrap("audit_seo", make_audit_seo_node()))
    graph.add_node(
        "generate_candidate_questions",
        wrap(
            "generate_candidate_questions",
            make_generate_candidate_questions_node(llm_client, reasoning_effort),
        ),
    )
    graph.add_node("validate_questions", wrap("validate_questions", make_validate_questions_node()))
    graph.add_node("assemble_questions", wrap("assemble_questions", make_assemble_questions_node()))
    graph.add_node("plan_media", wrap("plan_media", make_plan_media_node(llm_client, reasoning_effort)))
    graph.add_node("persist_finisher", wrap("persist_finisher", make_persist_finisher_node(repo)))

    graph.set_entry("audit_seo")
    graph.add_conditional_edge("audit_seo", _route_after_audit)
    graph.add_edge("generate_candidate_questions", "validate_questions")
    graph.add_edge("validate_questions", "assemble_questions")
    graph.add_edge("assemble_questions", "plan_media")
    graph.add_edge("plan_media", "persist_finisher")
    graph.add_edge("persist_finisher", END)

    return graph.compile()
