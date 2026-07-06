"""Step 1 — query construction. TOPIC_GENERATOR.md §3 step 1.

Autonomous mode is fully deterministic (no LLM call): rotate through every
`UpscSubject` value, one lightweight query per subject. Directed mode is one
LLM call expanding the editor's steering instruction into 2-4 concrete
queries — same pattern as the Researcher's `plan_queries`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.prompts.topic_generator import QUERY_EXPANSION_SYSTEM, build_query_expansion_user_prompt
from agents.shared.event_text import preview_queries
from agents.topic_generator.models import ExpandedQueries, TopicGeneratorMode, UpscSubject
from graph.engine import NodeFn
from llm.client import LLMClient

_SUBJECT_QUERY_HINTS: dict[UpscSubject, str] = {
    UpscSubject.POLITY_GOVERNANCE: "Indian polity and governance",
    UpscSubject.ECONOMY: "Indian economy and economic policy",
    UpscSubject.ENVIRONMENT_ECOLOGY: "environment and ecology in India",
    UpscSubject.SCIENCE_TECHNOLOGY: "science and technology in India",
    UpscSubject.GEOGRAPHY: "geography relevant to India",
    UpscSubject.HISTORY_CULTURE: "Indian history and culture",
    UpscSubject.INTERNATIONAL_RELATIONS: "India's international relations and foreign policy",
    UpscSubject.SOCIAL_JUSTICE: "social justice and welfare policy in India",
    UpscSubject.ETHICS: "ethics and public administration in India",
    UpscSubject.SECURITY_DISASTER_MGMT: "internal security and disaster management in India",
    UpscSubject.MISCELLANEOUS_CURRENT_AFFAIRS: "notable current affairs in India",
}


def _autonomous_queries() -> list[str]:
    return [f"Latest developments in {hint}, past month" for hint in _SUBJECT_QUERY_HINTS.values()]


def make_build_queries_node(llm_client: LLMClient) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        mode = TopicGeneratorMode(state["mode"])

        if mode is TopicGeneratorMode.AUTONOMOUS:
            queries = _autonomous_queries()
            summary = f"Built {len(queries)} subject-rotation queries: {preview_queries(queries)}"
            return {"queries": queries, "_event_summary": summary}

        user_instruction = state["user_instruction"]
        messages = [
            {"role": "system", "content": QUERY_EXPANSION_SYSTEM},
            {"role": "user", "content": build_query_expansion_user_prompt(user_instruction)},
        ]
        result: ExpandedQueries = await asyncio.to_thread(llm_client.reason, messages, ExpandedQueries)
        queries = list(result.queries)
        summary = f"Expanded instruction into {len(queries)} queries: {preview_queries(queries)}"
        return {"queries": queries, "_event_summary": summary}

    return node
