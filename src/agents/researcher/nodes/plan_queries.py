"""Step 1 — query planner. One LLM call: topic + audience tag -> 4-6
sub-questions covering distinct angles. RESEARCHER.md §3 step 1.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.prompts.researcher import PLAN_QUERIES_SYSTEM, build_plan_queries_user_prompt
from agents.researcher.models import PlannedSubQueries
from graph.engine import NodeFn
from llm.client import LLMClient


def make_plan_queries_node(llm_client: LLMClient) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        topic = state["topic"]
        audience_tag = state.get("audience_tag")

        messages = [
            {"role": "system", "content": PLAN_QUERIES_SYSTEM},
            {"role": "user", "content": build_plan_queries_user_prompt(topic, audience_tag)},
        ]
        result: PlannedSubQueries = await asyncio.to_thread(
            llm_client.reason, messages, PlannedSubQueries
        )

        return {
            "sub_queries_asked": list(result.sub_queries),
            "sub_queries_this_round": list(result.sub_queries),
            "iteration": 0,
            "sources": [],
            "claims": [],
            "source_summaries": {},
        }

    return node
