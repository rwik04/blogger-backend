"""Final node — assembles the `TopicGeneratorOutput` from state and persists
every candidate to the `topics` table via `TopicRepository`.

`auto_approve` (TOPIC_GENERATOR.md §1): marks the first surviving (i.e. not
`similar_to_existing`) candidate, in returned order, as `status='selected'`
at insert time. Doesn't itself trigger the Researcher — that's a deliberate
scope boundary consistent with this codebase's "no orchestrator chains
stages automatically" rule; a human or a future cron still calls the actual
select/run step next.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.topic_generator.models import DedupStatus, TopicCandidate, TopicGeneratorOutput
from db.repositories.topic_repository import TopicRepository
from graph.engine import NodeFn


def make_persist_node(repo: TopicRepository) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        batch_id = state["batch_id"]
        auto_approve = state.get("auto_approve", False)
        classified = state.get("classified_candidates", [])

        candidates = [TopicCandidate.model_validate(c) for c in classified]

        auto_selected_id: str | None = None
        if auto_approve:
            top = next((c for c in candidates if c.dedup_status != DedupStatus.SIMILAR_TO_EXISTING), None)
            if top is not None:
                auto_selected_id = top.candidate_id

        rows = [
            {**c.model_dump(mode="json"), "status": "selected" if c.candidate_id == auto_selected_id else "suggested"}
            for c in candidates
        ]
        await asyncio.to_thread(repo.save_candidates, batch_id, rows)

        output = TopicGeneratorOutput(batch_id=batch_id, mode=state["mode"], candidates=candidates)

        summary = f"Persisted {len(candidates)} candidate(s)"
        if auto_selected_id:
            summary += f", auto-selected {auto_selected_id}"

        return {"output": output.model_dump(mode="json"), "_event_summary": summary}

    return node
