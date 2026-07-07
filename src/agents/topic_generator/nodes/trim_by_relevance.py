"""Optional step between `classify` and `persist` — lets a caller cast a wide
search net (`count`) and still only keep the day's best candidates
(`max_output`). Used by the daily autonomous cron: `count` is set high across
all subjects, then only the top `max_output` by `relevance_score` survive
into the review queue. A no-op (passthrough) when `max_output` isn't set, so
manual/directed generation keeps today's keep-everything behavior.
"""

from __future__ import annotations

from typing import Any

from graph.engine import NodeFn


def make_trim_by_relevance_node() -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        classified = state.get("classified_candidates", [])
        max_output = state.get("max_output")

        if not max_output or len(classified) <= max_output:
            return {
                "classified_candidates": classified,
                "_event_summary": f"Keeping all {len(classified)} candidate(s) (no trim needed)",
            }

        trimmed = sorted(classified, key=lambda c: c.get("relevance_score", 0), reverse=True)[:max_output]
        summary = f"Trimmed {len(classified)} candidate(s) down to the top {len(trimmed)} by relevance"
        return {"classified_candidates": trimmed, "_event_summary": summary}

    return node
