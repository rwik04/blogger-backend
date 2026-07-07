"""Step 5 — classification + justification. TOPIC_GENERATOR.md §3 step 5:
one LLM call, over all surviving candidates together, assigns
`subject`/`gs_papers`/`why_this_topic`/`current_relevance`.

Every candidate from the round gets classified regardless of `dedup_status`
— duplicates are flagged, not hidden, per §8 ("never hide results from the
user, let them see and override the flag themselves").
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents.prompts.topic_generator import build_classify_user_prompt, CLASSIFY_SYSTEM
from agents.topic_generator.models import ClassifiedCandidateSet
from graph.engine import NodeFn
from llm.client import LLMClient

logger = logging.getLogger(__name__)


def make_classify_node(llm_client: LLMClient, reasoning_effort: str | None = "low") -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        dedup_results = state.get("dedup_results", [])

        if not dedup_results:
            return {"classified_candidates": [], "_event_summary": "No surviving candidates to classify"}

        messages = [
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": build_classify_user_prompt(dedup_results)},
        ]
        result: ClassifiedCandidateSet = await asyncio.to_thread(
            llm_client.reason, messages, ClassifiedCandidateSet, reasoning_effort
        )

        classifications = result.classifications
        if len(classifications) != len(dedup_results):
            # Repair by truncating/padding defensively rather than raising —
            # a length mismatch shouldn't fail the whole batch when most
            # candidates classified fine. Any unmatched candidate falls back
            # to the miscellaneous catch-all (TOPIC_GENERATOR.md §7).
            logger.warning(
                "classify returned %d classifications for %d candidates; falling back for the mismatch",
                len(classifications),
                len(dedup_results),
            )

        merged: list[dict[str, Any]] = []
        subjects_seen: set[str] = set()
        for i, candidate in enumerate(dedup_results):
            if i < len(classifications):
                classification = classifications[i]
                merged.append(
                    {
                        **candidate,
                        "subject": classification.subject.value,
                        "gs_papers": [p.value for p in classification.gs_papers],
                        "why_this_topic": classification.why_this_topic,
                        "current_relevance": classification.current_relevance,
                        "relevance_score": classification.relevance_score,
                    }
                )
                subjects_seen.add(classification.subject.value)
            else:
                merged.append(
                    {
                        **candidate,
                        "subject": "miscellaneous_current_affairs",
                        "gs_papers": ["prelims_only"],
                        "why_this_topic": candidate["one_line_summary"],
                        "current_relevance": candidate["one_line_summary"],
                        "relevance_score": 40,
                    }
                )

        summary = f"Tagged {len(merged)} candidates across {len(subjects_seen) or 1} subject area(s)"
        return {"classified_candidates": merged, "_event_summary": summary}

    return node
