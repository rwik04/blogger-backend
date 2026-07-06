"""Final node — writes the assembled `ResearchBrief` to the normalized
research tables plus `agent_steps.output`. RESEARCHER.md §5."""

from __future__ import annotations

import asyncio
from typing import Any

from db.repositories.research_repository import ResearchRepository
from graph.engine import NodeFn


def make_persist_brief_node(repo: ResearchRepository) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        brief = state["brief"]
        await asyncio.to_thread(repo.save_research_brief, brief)
        summary = f"Saved research brief ({len(brief.get('sources', []))} source(s)) to the database"
        return {"status": "done", "_event_summary": summary}

    return node
