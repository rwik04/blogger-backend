"""Step 1 — the single `draft_plan` LLM call. STRATEGIST.md §2: keyword
selection and outlining happen together in one structured response, at
`reasoning_effort="low"` since this is a small, well-grounded task rather
than one needing deep reasoning.

Post-parse, a couple of business rules that the JSON schema itself can't
express are checked in plain Python — an outline too short, or missing
`target_keyword` on too many sections, is the one thing downstream (Writer)
can't proceed without. One repair retry, quoting the specific failure,
before giving up (STRATEGIST.md §6).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents.prompts.strategist import DRAFT_PLAN_SYSTEM, build_draft_plan_user_prompt, build_repair_prompt
from agents.researcher.models import Claim, Source
from agents.strategist.models import DraftedPlan
from graph.engine import NodeFn
from llm.client import LLMClient

logger = logging.getLogger(__name__)

_MIN_OUTLINE_SECTIONS = 3
_MAX_MISSING_KEYWORD_FRACTION = 0.5


def check_business_rules(plan: DraftedPlan) -> str | None:
    """Returns a description of the first business-rule violation found, or
    `None` if the plan is acceptable. Only checks what the JSON schema
    itself can't express — structural validity is already guaranteed by
    `LLMClient.reason()`'s strict-schema parsing.
    """
    if len(plan.outline) < _MIN_OUTLINE_SECTIONS:
        return f"The outline has only {len(plan.outline)} section(s); at least {_MIN_OUTLINE_SECTIONS} are required."

    missing = sum(1 for section in plan.outline if not section.target_keyword)
    if missing / len(plan.outline) > _MAX_MISSING_KEYWORD_FRACTION:
        return (
            f"{missing} of {len(plan.outline)} outline sections are missing a target_keyword; "
            "more than half must have one."
        )

    return None


def make_draft_plan_node(llm_client: LLMClient, reasoning_effort: str | None = "low") -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        research_brief = state["research_brief"]
        claims = [Claim.model_validate(c) for c in research_brief["claims"]]
        sources = [Source.model_validate(s) for s in research_brief["sources"]]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": DRAFT_PLAN_SYSTEM},
            {
                "role": "user",
                "content": build_draft_plan_user_prompt(
                    topic=state["topic"],
                    audience_tag=state.get("audience_tag"),
                    claims=claims,
                    sources=sources,
                ),
            },
        ]

        plan: DraftedPlan = await asyncio.to_thread(llm_client.reason, messages, DraftedPlan, reasoning_effort)
        issue = check_business_rules(plan)

        if issue is not None:
            logger.warning("draft_plan business-rule check failed, retrying once: %s", issue)
            messages.append({"role": "assistant", "content": plan.model_dump_json()})
            messages.append({"role": "user", "content": build_repair_prompt(issue)})
            plan = await asyncio.to_thread(llm_client.reason, messages, DraftedPlan, reasoning_effort)
            issue = check_business_rules(plan)
            if issue is not None:
                raise ValueError(f"draft_plan failed its business-rule check after one repair retry: {issue}")

        summary = (
            f"{plan.primary_keyword!r} + {len(plan.secondary_keywords)} secondary, "
            f"{len(plan.outline)}-section outline"
        )
        return {"drafted_plan": plan.model_dump(), "_event_summary": summary}

    return node
