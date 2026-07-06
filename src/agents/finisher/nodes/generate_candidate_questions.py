"""Step 1 of the quiz pipeline — over-generates UPSC-style candidate
questions in a single LLM call (FINISHER.md §2 step 1). Over-generating
roughly 2x the target count up front is cheaper than generating one at a
time and retrying — most quality loss happens at validation, so having
spare candidates to select from beats regenerating from scratch.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.finisher.models import DraftedQuestionSet
from agents.prompts.finisher import GENERATE_CANDIDATES_SYSTEM, build_generate_candidates_user_prompt
from agents.researcher.models import Claim
from agents.strategist.models import OutlineSection
from graph.engine import NodeFn
from llm.client import LLMClient

_OVERGENERATION_MULTIPLIER = 2
_TARGET_QUESTION_COUNT = 4


def make_generate_candidate_questions_node(
    llm_client: LLMClient,
    reasoning_effort: str | None = "medium",
    target_question_count: int = _TARGET_QUESTION_COUNT,
) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        outline = [OutlineSection.model_validate(s) for s in state["strategist_output"]["outline"]]
        claims = [Claim.model_validate(c) for c in state["research_brief"]["claims"]]
        candidate_count = target_question_count * _OVERGENERATION_MULTIPLIER

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GENERATE_CANDIDATES_SYSTEM},
            {
                "role": "user",
                "content": build_generate_candidates_user_prompt(
                    topic=state["topic"],
                    audience_tag=state.get("audience_tag"),
                    outline=outline,
                    claims=claims,
                    candidate_count=candidate_count,
                ),
            },
        ]

        drafted: DraftedQuestionSet = await asyncio.to_thread(
            llm_client.reason, messages, DraftedQuestionSet, reasoning_effort
        )

        summary = f"{len(drafted.questions)} candidate question(s) drafted"
        return {
            "candidate_questions": [q.model_dump() for q in drafted.questions],
            "_event_summary": summary,
        }

    return node
