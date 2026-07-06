"""Step 3 — candidate extraction. TOPIC_GENERATOR.md §3 step 3: one LLM call
over all search results together, returns N distinct topic candidates.

Also handles the all-duplicates retry (§8): if `route_after_dedup` looped
back here with `diversity_nudge_titles` staged in state, the extraction
prompt is nudged away from those already-covered titles.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from agents.prompts.topic_generator import build_extract_candidates_system_prompt, build_extract_candidates_user_prompt
from agents.topic_generator.models import ExtractedCandidateSet
from graph.engine import NodeFn
from llm.client import LLMClient

_MAX_SEARCH_RESULTS_FOR_EXTRACTION = 40
"""Caps prompt size regardless of how many queries fanned out (11 subjects x
5 results in autonomous mode would otherwise be 55 results in one call)."""


def _flatten_hits(search_rounds: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen_urls: set[str] = set()
    flattened: list[dict[str, str]] = []
    for round_result in search_rounds:
        for hit in round_result.get("hits", []):
            url = hit.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            flattened.append(hit)
    return flattened[:_MAX_SEARCH_RESULTS_FOR_EXTRACTION]


def make_extract_candidates_node(llm_client: LLMClient, reasoning_effort: str | None = "low") -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        search_rounds = state.get("search_rounds", [])
        search_results = _flatten_hits(search_rounds)
        count = state["count"]
        diversity_nudge_titles = state.get("diversity_nudge_titles")

        if not search_results:
            return {
                "extracted_candidates": [],
                "_event_summary": "No search results available to extract candidates from",
            }

        messages = [
            {"role": "system", "content": build_extract_candidates_system_prompt(count)},
            {
                "role": "user",
                "content": build_extract_candidates_user_prompt(count, search_results, diversity_nudge_titles),
            },
        ]
        result: ExtractedCandidateSet = await asyncio.to_thread(
            llm_client.reason, messages, ExtractedCandidateSet, reasoning_effort
        )

        extracted = [
            {
                "candidate_id": str(uuid.uuid4()),
                "title": candidate.title,
                "one_line_summary": candidate.one_line_summary,
                "trigger_source_url": candidate.trigger_source_url,
            }
            for candidate in result.candidates[:count]
        ]

        return {
            "extracted_candidates": extracted,
            "_event_summary": f"Found {len(extracted)} candidate topics",
        }

    return node
