"""Final node — assembles the `FinisherOutput` from state and persists it via
`FinisherRepository`. FINISHER.md §5/§6.

`final_title`/`final_tags`/`subject` are derived deterministically here
(no extra LLM call) straight from the Strategist's `SeoPlan` — FINISHER.md
doesn't specify how these are produced, and everything needed already
exists on the plan.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.finisher.models import FinisherOutput, MediaPrompt, SeoAudit, UpscStyleQuestion
from db.repositories.finisher_repository import FinisherRepository
from graph.engine import NodeFn

_MAX_TAGS = 10


def dedupe_tags(tags: list[str], max_tags: int = _MAX_TAGS) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(tag.strip())
        if len(result) >= max_tags:
            break
    return result


def make_persist_finisher_node(repo: FinisherRepository) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        run_id = state["run_id"]
        seo_plan = state["strategist_output"]["seo_plan"]

        output = FinisherOutput(
            run_id=run_id,
            seo_audit=SeoAudit.model_validate(state["seo_audit"]),
            questions=[UpscStyleQuestion.model_validate(q) for q in state.get("questions", [])],
            media=[MediaPrompt.model_validate(m) for m in state.get("media", [])],
            final_title=seo_plan["meta_title"],
            final_tags=dedupe_tags(seo_plan["secondary_keywords"]),
            subject=state.get("audience_tag") or "General",
            quality_flags=state.get("quality_flags", []),
        )

        await asyncio.to_thread(repo.save_finisher_output, output.model_dump())

        summary = (
            f"{len(output.questions)} quiz question(s), {len(output.media)} media prompt(s), "
            f"{len(output.seo_audit.heading_issues)} heading issue(s)"
        )
        return {"output": output.model_dump(), "status": "done", "_event_summary": summary}

    return node
