"""Shared draft-with-retries helper used by both `write_section.py` (per-section
drafting within the main Writer graph) and `edit_section.py` (one-shot section
rewrite). Extracted so both call sites run identical gap-retry/length-retry
logic (WRITER.md §8/§10) instead of duplicating it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable

from agents.prompts.writer import build_gap_repair_prompt, build_length_repair_prompt
from agents.writer.models import DraftedSection
from graph.events import EventEmitter
from llm.client import LLMClient

_MAX_GAP_RETRIES = 2
_MAX_LENGTH_RETRIES = 1
_MIN_WORD_COUNT = 50


def word_count(text: str) -> int:
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


async def draft_with_retries(
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
    wc = word_count(drafted.body_markdown)
    while wc < _MIN_WORD_COUNT and length_attempt < _MAX_LENGTH_RETRIES:
        length_attempt += 1
        retries_used += 1
        await _emit_retry(
            emitter,
            run_id,
            section_index,
            total_sections,
            length_attempt,
            _MAX_LENGTH_RETRIES,
            f"section too short ({wc} words, minimum {_MIN_WORD_COUNT})",
        )
        messages.append({"role": "assistant", "content": drafted.model_dump_json()})
        messages.append({"role": "user", "content": build_length_repair_prompt(_MIN_WORD_COUNT, wc)})
        drafted = await asyncio.to_thread(llm_client.reason, messages, DraftedSection, reasoning_effort)
        wc = word_count(drafted.body_markdown)

    return drafted, retries_used
