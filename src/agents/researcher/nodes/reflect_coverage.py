"""The reflection step that drives the iterative loop. Evaluated over the
*compacted* memory only (sub-questions asked, cumulative claims) — never over
raw source text, which is the whole point of compacting in `compact_round`
before this node ever runs.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.prompts.researcher import REFLECT_COVERAGE_SYSTEM, build_reflect_coverage_user_prompt
from agents.shared.event_text import preview_queries
from agents.researcher.models import ReflectDecision
from graph.engine import NodeFn
from llm.client import LLMClient


def make_reflect_coverage_node(llm_client: LLMClient) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": REFLECT_COVERAGE_SYSTEM},
            {"role": "user", "content": build_reflect_coverage_user_prompt(state)},
        ]
        result: ReflectDecision = await asyncio.to_thread(llm_client.reason, messages, ReflectDecision)

        summary = f"Decision: {result.decision} — {result.reasoning}"
        if result.decision == "continue" and result.next_sub_queries:
            summary += f". Next: {preview_queries(result.next_sub_queries)}"

        return {
            "reflect_decision": result.decision,
            "reflect_reasoning": result.reasoning,
            "sub_queries_this_round": result.next_sub_queries,
            "_event_summary": summary,
        }

    return node
