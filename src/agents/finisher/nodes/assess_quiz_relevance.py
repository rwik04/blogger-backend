"""Gate that runs before the quiz-generation steps — a single LLM call
deciding whether the topic's actual researched claims have enough concrete,
checkable factual density to support a good UPSC-style statement-based quiz
at all. `include_quiz` (the user/config toggle) says the caller *wants* a
quiz if one makes sense; this node makes the "does it actually make sense
for this topic" call, so narrative/opinion-heavy topics don't get a forced,
weak quiz bolted on. See `pipeline.py`'s routing after `audit_seo`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.finisher.models import QuizRelevanceAssessment
from agents.prompts.finisher import ASSESS_QUIZ_RELEVANCE_SYSTEM, build_assess_quiz_relevance_user_prompt
from agents.researcher.models import Claim
from agents.strategist.models import OutlineSection
from graph.engine import NodeFn
from llm.client import LLMClient


def make_assess_quiz_relevance_node(llm_client: LLMClient, reasoning_effort: str | None = "medium") -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        outline = [OutlineSection.model_validate(s) for s in state["strategist_output"]["outline"]]
        claims = [Claim.model_validate(c) for c in state["research_brief"]["claims"]]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ASSESS_QUIZ_RELEVANCE_SYSTEM},
            {
                "role": "user",
                "content": build_assess_quiz_relevance_user_prompt(
                    topic=state["topic"],
                    audience_tag=state.get("audience_tag"),
                    outline=outline,
                    claims=claims,
                ),
            },
        ]

        assessment: QuizRelevanceAssessment = await asyncio.to_thread(
            llm_client.reason, messages, QuizRelevanceAssessment, reasoning_effort
        )

        quality_flags = list(state.get("quality_flags", []))
        if not assessment.quiz_relevant:
            quality_flags.append(f"Quiz skipped — not relevant for this topic: {assessment.reason}")

        summary = f"{'relevant' if assessment.quiz_relevant else 'not relevant'} — {assessment.reason}"
        return {
            "quiz_relevant": assessment.quiz_relevant,
            "quiz_relevance_reason": assessment.reason,
            "quality_flags": quality_flags,
            "_event_summary": summary,
        }

    return node
