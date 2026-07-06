"""Media prompt planning (FINISHER.md §4). One LLM call producing a banner
prompt plus up to a couple of infographic prompts; which sections get an
infographic is a deterministic pick (must have a `target_keyword` and an
above-median word count) — the LLM only writes the prompt/alt text, never
the section selection.
"""

from __future__ import annotations

import asyncio
import statistics
import uuid
from typing import Any

from agents.finisher.models import DraftedMediaPlan, MediaPrompt
from agents.prompts.finisher import PLAN_MEDIA_SYSTEM, build_plan_media_user_prompt
from agents.strategist.models import OutlineSection, SeoPlan
from agents.writer.models import SectionResult
from graph.engine import NodeFn
from llm.client import LLMClient

_MAX_INFOGRAPHIC_SECTIONS = 2


def pick_infographic_sections(
    sections: list[SectionResult],
    outline: list[OutlineSection],
    max_sections: int = _MAX_INFOGRAPHIC_SECTIONS,
) -> list[SectionResult]:
    keyword_by_section = {s.section_id: s.target_keyword for s in outline}
    keyworded = [s for s in sections if keyword_by_section.get(s.section_id)]
    if not keyworded:
        return []

    median_words = statistics.median(s.word_count for s in keyworded)
    eligible = [s for s in keyworded if s.word_count >= median_words]
    eligible.sort(key=lambda s: s.word_count, reverse=True)
    return eligible[:max_sections]


def make_plan_media_node(llm_client: LLMClient, reasoning_effort: str | None = "medium") -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        sections = [SectionResult.model_validate(s) for s in state["writer_output"]["sections"]]
        outline = [OutlineSection.model_validate(s) for s in state["strategist_output"]["outline"]]
        seo_plan = SeoPlan.model_validate(state["strategist_output"]["seo_plan"])

        infographic_sections = pick_infographic_sections(sections, outline)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": PLAN_MEDIA_SYSTEM},
            {
                "role": "user",
                "content": build_plan_media_user_prompt(
                    topic=state["topic"], seo_plan=seo_plan, infographic_sections=infographic_sections
                ),
            },
        ]

        drafted: DraftedMediaPlan = await asyncio.to_thread(
            llm_client.reason, messages, DraftedMediaPlan, reasoning_effort
        )

        media = [
            MediaPrompt(
                media_id=str(uuid.uuid4()),
                kind=item.kind,
                section_id=item.section_id,
                prompt=item.prompt,
                alt_text=item.alt_text,
            )
            for item in drafted.media
        ]

        banner_count = sum(1 for m in media if m.kind == "banner")
        infographic_count = sum(1 for m in media if m.kind == "infographic")
        summary = f"{banner_count} banner + {infographic_count} infographic prompt(s)"

        return {"media": [m.model_dump() for m in media], "_event_summary": summary}

    return node
