"""Final node — assembles the `StrategistOutput` from state and persists it
via `StrategistRepository`. STRATEGIST.md §4."""

from __future__ import annotations

import asyncio
from typing import Any

from agents.strategist.models import OutlineSection, SeoPlan, StrategistOutput
from db.repositories.strategist_repository import StrategistRepository
from graph.engine import NodeFn


def make_persist_plan_node(repo: StrategistRepository) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        drafted_plan = state["drafted_plan"]

        seo_plan = SeoPlan(
            primary_keyword=drafted_plan["primary_keyword"],
            secondary_keywords=drafted_plan["secondary_keywords"],
            meta_title=drafted_plan["meta_title"],
            meta_description=drafted_plan["meta_description"],
            slug=drafted_plan["slug"],
        )
        outline = [OutlineSection.model_validate(section) for section in drafted_plan["outline"]]

        output = StrategistOutput(
            run_id=state["run_id"],
            seo_plan=seo_plan,
            outline=outline,
            narrative_angle=drafted_plan["narrative_angle"],
        )

        await asyncio.to_thread(repo.save_strategist_output, output.model_dump())
        return {"output": output.model_dump(), "status": "done"}

    return node
