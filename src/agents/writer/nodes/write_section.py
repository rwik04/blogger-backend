"""The Writer's only real step, run once per outline section via a
self-looping graph edge (`route_after_section`) — mirrors the shape of
`agents.researcher.nodes.reflect_coverage` / `route_after_reflect`, but the
loop variable here is "which section are we on" instead of "which research
round".

Per WRITER.md §2: one LLM call drafts, self-fact-checks, and humanizes a
section together. Two independently-budgeted internal retry loops follow
(§8/§10):
  - up to `_MAX_GAP_RETRIES` retries while `unsupported_gaps` is non-empty
  - up to `_MAX_LENGTH_RETRIES` retries (kept separate) if the body comes
    out under `_MIN_WORD_COUNT` words

Section-level failure handling (§8): if the LLM call itself keeps failing
(schema/parse errors, provider errors) even after retries are exhausted,
this node does not raise on the first such failure — it's logged, added to
`needs_more_research`, and `consecutive_section_failures` is incremented so
`route_after_section` can still advance to the next section. Only a second
consecutive full-section failure raises, which `with_events` turns into a
`failed` event and stops the run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable

from agents.prompts.writer import (
    WRITE_SECTION_SYSTEM,
    build_gap_repair_prompt,
    build_length_repair_prompt,
    build_write_section_user_prompt,
)
from agents.researcher.models import Claim
from agents.strategist.models import OutlineSection
from agents.writer.models import DraftedSection, SectionResult
from graph.engine import NodeFn
from graph.events import EventEmitter
from llm.client import LLMClient

logger = logging.getLogger(__name__)

_MAX_GAP_RETRIES = 2
_MAX_LENGTH_RETRIES = 1
_MIN_WORD_COUNT = 50
_MAX_CONSECUTIVE_FAILURES = 2


def _word_count(text: str) -> int:
    return len(text.split())


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None and hasattr(value, "__await__"):
        await value


async def _emit_retry(
    emitter: EventEmitter | None,
    run_id: str | None,
    section_index: int,
    total_sections: int,
    attempt: int,
    max_attempts: int,
    reason: str,
) -> None:
    if emitter is None:
        return
    detail = {
        "section_index": section_index,
        "total_sections": total_sections,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "reason": reason,
    }
    await _maybe_await(emitter(run_id, "section_retry", "info", detail))


async def _draft_with_retries(
    llm_client: LLMClient,
    messages: list[dict[str, Any]],
    reasoning_effort: str | None,
    emitter: EventEmitter | None,
    run_id: str | None,
    section_index: int,
    total_sections: int,
) -> tuple[DraftedSection, int]:
    """Runs the initial draft call, then the two independent retry loops.
    Returns the final `DraftedSection` and the total number of retries used
    (gap-retries + length-retries combined, 0-3).
    """
    drafted: DraftedSection = await asyncio.to_thread(llm_client.reason, messages, DraftedSection, reasoning_effort)
    retries_used = 0

    gap_attempt = 0
    while drafted.unsupported_gaps and gap_attempt < _MAX_GAP_RETRIES:
        gap_attempt += 1
        retries_used += 1
        await _emit_retry(
            emitter,
            run_id,
            section_index,
            total_sections,
            gap_attempt,
            _MAX_GAP_RETRIES,
            f"reworking unverifiable claim(s): {'; '.join(drafted.unsupported_gaps)}",
        )
        messages.append({"role": "assistant", "content": drafted.model_dump_json()})
        messages.append({"role": "user", "content": build_gap_repair_prompt(drafted.unsupported_gaps)})
        drafted = await asyncio.to_thread(llm_client.reason, messages, DraftedSection, reasoning_effort)

    length_attempt = 0
    word_count = _word_count(drafted.body_markdown)
    while word_count < _MIN_WORD_COUNT and length_attempt < _MAX_LENGTH_RETRIES:
        length_attempt += 1
        retries_used += 1
        await _emit_retry(
            emitter,
            run_id,
            section_index,
            total_sections,
            length_attempt,
            _MAX_LENGTH_RETRIES,
            f"section too short ({word_count} words, minimum {_MIN_WORD_COUNT})",
        )
        messages.append({"role": "assistant", "content": drafted.model_dump_json()})
        messages.append({"role": "user", "content": build_length_repair_prompt(_MIN_WORD_COUNT, word_count)})
        drafted = await asyncio.to_thread(llm_client.reason, messages, DraftedSection, reasoning_effort)
        word_count = _word_count(drafted.body_markdown)

    return drafted, retries_used


def make_write_section_node(
    llm_client: LLMClient,
    reasoning_effort: str | None = "medium",
    emitter: EventEmitter | None = None,
) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        outline = [OutlineSection.model_validate(s) for s in state["outline"]]
        claims = [Claim.model_validate(c) for c in state["research_brief"]["claims"]]
        valid_claim_ids = {c.id for c in claims}

        run_id = state.get("run_id")
        index = state["current_section_index"]
        total_sections = len(outline)
        section = outline[index]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": WRITE_SECTION_SYSTEM},
            {
                "role": "user",
                "content": build_write_section_user_prompt(
                    topic=state["topic"],
                    audience_tag=state.get("audience_tag"),
                    outline=outline,
                    claims=claims,
                    draft_so_far=state.get("draft_so_far", ""),
                    section=section,
                ),
            },
        ]

        try:
            drafted, retries_used = await _draft_with_retries(
                llm_client, messages, reasoning_effort, emitter, run_id, index, total_sections
            )
        except Exception as exc:
            logger.exception(
                "write_section failed outright for section_id=%s (index=%d/%d)",
                section.section_id,
                index,
                total_sections,
            )
            failures = state.get("consecutive_section_failures", 0) + 1
            if failures >= _MAX_CONSECUTIVE_FAILURES:
                raise RuntimeError(
                    f"{_MAX_CONSECUTIVE_FAILURES} consecutive sections failed outright "
                    f"(latest: {section.section_id}: {exc}); failing the Writer run."
                ) from exc

            needs_more_research = state.get("needs_more_research", []) + [
                f"{section.section_id}: section failed to generate ({exc})"
            ]
            return {
                "consecutive_section_failures": failures,
                "needs_more_research": needs_more_research,
                "_event_summary": f"Section {index + 1}/{total_sections} failed to generate — skipped",
            }

        filtered_claim_ids = [cid for cid in drafted.claim_ids if cid in valid_claim_ids]
        word_count = _word_count(drafted.body_markdown)

        needs_more_research = list(state.get("needs_more_research", []))
        needs_more_research.extend(f"{section.section_id}: {gap}" for gap in drafted.unsupported_gaps)

        section_result = SectionResult(
            section_id=section.section_id,
            heading=section.heading,
            body_markdown=drafted.body_markdown,
            claim_ids=filtered_claim_ids,
            unsupported_gaps=drafted.unsupported_gaps,
            tone_notes=drafted.tone_notes,
            word_count=word_count,
            retries_used=retries_used,
        )

        sections = state.get("sections", []) + [section_result.model_dump()]
        draft_so_far = (state.get("draft_so_far", "") + f"\n\n## {section.heading}\n\n{drafted.body_markdown}").strip()

        summary = (
            f"Section {index + 1}/{total_sections} drafted, checked, and polished "
            f"({word_count} words, {len(filtered_claim_ids)} claims, {len(drafted.unsupported_gaps)} gaps)"
        )

        return {
            "sections": sections,
            "draft_so_far": draft_so_far,
            "needs_more_research": needs_more_research,
            "consecutive_section_failures": 0,
            "_event_summary": summary,
        }

    return node


def route_after_section(state: dict[str, Any]) -> str:
    """The loop-back edge — advances to the next outline section, or moves
    on to `persist_draft` once every section has been written. Mirrors
    `route_after_reflect` in `agents.researcher.pipeline`.
    """
    outline = state["outline"]
    index = state["current_section_index"]

    if index + 1 < len(outline):
        state["current_section_index"] = index + 1
        return "write_section"
    return "persist_draft"
