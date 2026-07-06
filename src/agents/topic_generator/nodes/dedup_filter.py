"""Step 4 — dedup filter. TOPIC_GENERATOR.md §4: trigram similarity against
topic history first (cheap, deterministic), LLM tiebreak only for the
genuinely ambiguous middle band. Also owns the all-duplicates retry loop
(§8): `route_after_dedup` sends the pipeline back to `extract_candidates`
once, with a diversity nudge, if every candidate in a round came back
`similar_to_existing`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents.prompts.topic_generator import build_dedup_tiebreak_user_prompt, DEDUP_TIEBREAK_SYSTEM
from agents.topic_generator.models import DedupStatus, DedupTiebreakDecision
from db.repositories.topic_repository import TopicRepository
from graph.engine import NodeFn
from llm.client import LLMClient

logger = logging.getLogger(__name__)

_SIMILAR_THRESHOLD = 0.4
_AMBIGUOUS_THRESHOLD = 0.25


async def _classify_dedup_status(
    llm_client: LLMClient, candidate: dict[str, Any], repo: TopicRepository, reasoning_effort: str | None
) -> tuple[str, float | None]:
    matches = await asyncio.to_thread(repo.find_similar_topics, candidate["title"])
    if not matches:
        return DedupStatus.NEW.value, None

    top_match = matches[0]
    score = float(top_match["similarity_score"])

    if score >= _SIMILAR_THRESHOLD:
        return DedupStatus.SIMILAR_TO_EXISTING.value, score

    if score >= _AMBIGUOUS_THRESHOLD:
        try:
            messages = [
                {"role": "system", "content": DEDUP_TIEBREAK_SYSTEM},
                {
                    "role": "user",
                    "content": build_dedup_tiebreak_user_prompt(
                        candidate["title"], candidate["one_line_summary"], top_match["title"]
                    ),
                },
            ]
            decision: DedupTiebreakDecision = await asyncio.to_thread(
                llm_client.reason, messages, DedupTiebreakDecision, reasoning_effort
            )
            status = DedupStatus.SIMILAR_TO_EXISTING if decision.same_underlying_story else DedupStatus.NEW
            return status.value, score
        except Exception:
            logger.exception("Dedup tiebreak LLM call failed for candidate %r; flagging for review", candidate["title"])
            return DedupStatus.NEEDS_REVIEW.value, score

    return DedupStatus.NEW.value, score


def make_dedup_filter_node(
    llm_client: LLMClient, repo: TopicRepository, reasoning_effort: str | None = "low"
) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        extracted = state.get("extracted_candidates", [])

        dedup_results = []
        for candidate in extracted:
            dedup_status, similarity_score = await _classify_dedup_status(
                llm_client, candidate, repo, reasoning_effort
            )
            dedup_results.append({**candidate, "dedup_status": dedup_status, "similarity_score": similarity_score})

        dropped = sum(1 for c in dedup_results if c["dedup_status"] == DedupStatus.SIMILAR_TO_EXISTING.value)
        needs_review = sum(1 for c in dedup_results if c["dedup_status"] == DedupStatus.NEEDS_REVIEW.value)
        new = len(dedup_results) - dropped - needs_review
        summary = f"{dropped} dropped as duplicates, {needs_review} flagged for review, {new} new"

        return {"dedup_results": dedup_results, "_event_summary": summary}

    return node


def route_after_dedup(state: dict[str, Any]) -> str:
    dedup_results = state.get("dedup_results", [])
    already_retried = state.get("diversity_nudge_attempted", False)

    all_duplicates = bool(dedup_results) and all(
        c["dedup_status"] == DedupStatus.SIMILAR_TO_EXISTING.value for c in dedup_results
    )

    if all_duplicates and not already_retried:
        state["diversity_nudge_attempted"] = True
        state["diversity_nudge_titles"] = [c["title"] for c in dedup_results]
        return "extract_candidates"

    return "classify"
