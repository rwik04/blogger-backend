"""Final node — assembles the `WriterOutput` from state and persists it via
`WriterRepository`. WRITER.md §4/§6.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.writer.models import SectionResult, WriterOutput
from db.repositories.writer_repository import WriterRepository
from graph.engine import NodeFn


def make_persist_draft_node(repo: WriterRepository) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        run_id = state["run_id"]
        needs_more_research = state.get("needs_more_research", [])

        draft_version = await asyncio.to_thread(repo.get_next_draft_version, run_id)

        output = WriterOutput(
            run_id=run_id,
            draft_version=draft_version,
            sections=[SectionResult.model_validate(s) for s in state.get("sections", [])],
            needs_more_research=needs_more_research,
        )

        await asyncio.to_thread(repo.save_writer_output, output.model_dump())

        total_words = sum(section.word_count for section in output.sections)
        summary = f"Draft complete: {len(output.sections)} sections, {total_words} words"
        if needs_more_research:
            summary += f", {len(needs_more_research)} unresolved gap(s) flagged for research"

        return {"output": output.model_dump(), "status": "done", "_event_summary": summary}

    return node
