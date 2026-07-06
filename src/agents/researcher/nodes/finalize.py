"""Terminal nodes: `finalize_brief` assembles the `ResearchBrief` from
cumulative (already-compacted) state, and `fail_step` marks a run
`needs_review`. The hard-fail threshold from RESEARCHER.md §8 ("fewer than 3
total sources survive filtering") is checked here, after the loop ends,
since sources now accumulate across every round rather than a single pass.
"""

from __future__ import annotations

from typing import Any

from agents.researcher.models import ResearchBrief, Source
from graph.engine import NodeFn

_MIN_SOURCES = 3


def make_finalize_brief_node() -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        brief = ResearchBrief(
            run_id=state["run_id"],
            sub_queries=state.get("sub_queries_asked", []),
            sources=state.get("sources", []),
            claims=state.get("claims", []),
        )
        summary = f"Finalized brief: {len(brief.sources)} source(s), {len(brief.claims)} claim(s)"
        return {"brief": brief.model_dump(), "status": "extracted", "_event_summary": summary}

    return node


def route_after_finalize(state: dict[str, Any]) -> str:
    sources: list[Source] = state.get("sources", [])
    if len(sources) < _MIN_SOURCES:
        state["error"] = (
            f"Only {len(sources)} source(s) survived filtering across "
            f"{state.get('iteration', 0) + 1} round(s); minimum is {_MIN_SOURCES} "
            "for a defensible brief"
        )
        return "fail_step"
    return "write_report"


def make_fail_step_node() -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        return {"status": "needs_review"}

    return node
