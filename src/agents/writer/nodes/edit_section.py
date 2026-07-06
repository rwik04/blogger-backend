"""One-shot rewrite of a single section of the latest draft — the API's
section-edit capability. Unlike `write_section`, this isn't a graph node (no
looping needed for a single operation): it's a plain async function called
directly by `Writer.edit_section`.

Flow (plan §"Section-edit design"):
1. Load the latest draft's sections via `WriterRepository.load_latest_draft`.
2. Build `draft_so_far` from every *other* current section, reuse the same
   `DraftedSection` schema + gap-retry/length-retry loop as `write_section`
   (shared via `agents.writer.nodes.drafting`).
3. Replace just the edited section in the full ordered list, bump
   `draft_version`, and persist through the existing, unmodified
   `WriterRepository.save_writer_output` — a new draft version with one
   section changed is exactly what that method already does.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents.prompts.writer import (
    EDIT_PRESET_INSTRUCTIONS,
    EDIT_SECTION_SYSTEM,
    build_edit_section_user_prompt,
)
from agents.researcher.models import Claim
from agents.strategist.models import OutlineSection
from agents.writer.models import EditPreset, EditSectionInput, SectionResult, WriterOutput
from agents.writer.nodes.drafting import draft_with_retries, word_count as _word_count
from db.repositories.errors import SectionNotFoundError, WriterOutputNotFoundError
from db.repositories.writer_repository import WriterRepository
from graph.events import EventEmitter
from llm.client import LLMClient

logger = logging.getLogger(__name__)


def _resolve_instruction(preset: EditPreset, extra_instruction: str | None) -> str:
    if preset is EditPreset.CUSTOM:
        assert extra_instruction is not None  # enforced by EditSectionInput's validator
        return extra_instruction.strip()

    base = EDIT_PRESET_INSTRUCTIONS[preset.value]
    if extra_instruction and extra_instruction.strip():
        return f"{base} Additionally: {extra_instruction.strip()}"
    return base


async def edit_section(
    llm_client: LLMClient,
    repo: WriterRepository,
    input: EditSectionInput,
    reasoning_effort: str | None = "medium",
    emitter: EventEmitter | None = None,
) -> WriterOutput:
    outline = list(input.strategist_output.outline)
    claims = list(input.research_brief.claims)
    valid_claim_ids = {c.id for c in claims}

    latest_draft = await asyncio.to_thread(repo.load_latest_draft, input.run_id)
    if latest_draft is None:
        raise WriterOutputNotFoundError(
            f"No persisted draft for run_id={input.run_id!r} — run the Writer agent first"
        )

    current_sections: list[dict[str, Any]] = latest_draft["sections"]
    target_index = next(
        (i for i, s in enumerate(current_sections) if s["section_id"] == input.section_id), None
    )
    if target_index is None:
        raise SectionNotFoundError(
            f"section_id={input.section_id!r} not found in latest draft (run_id={input.run_id!r})"
        )

    target_section = current_sections[target_index]
    outline_section: OutlineSection | None = next(
        (s for s in outline if s.section_id == input.section_id), None
    )
    if outline_section is None:
        raise SectionNotFoundError(
            f"section_id={input.section_id!r} not found in the run's outline (run_id={input.run_id!r})"
        )

    draft_so_far = "\n\n".join(
        f"## {s['heading']}\n\n{s['body_markdown']}"
        for i, s in enumerate(current_sections)
        if i != target_index
    ).strip()

    instruction = _resolve_instruction(input.preset, input.instruction)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": EDIT_SECTION_SYSTEM},
        {
            "role": "user",
            "content": build_edit_section_user_prompt(
                topic=input.topic,
                audience_tag=input.audience_tag,
                outline=outline,
                claims=claims,
                draft_so_far=draft_so_far,
                section=outline_section,
                current_body_markdown=target_section["body_markdown"],
                instruction=instruction,
            ),
        },
    ]

    drafted, retries_used = await draft_with_retries(
        llm_client, messages, reasoning_effort, emitter, input.run_id, target_index, len(current_sections)
    )

    filtered_claim_ids = [cid for cid in drafted.claim_ids if cid in valid_claim_ids]
    word_count = _word_count(drafted.body_markdown)

    edited_result = SectionResult(
        section_id=outline_section.section_id,
        heading=outline_section.heading,
        body_markdown=drafted.body_markdown,
        claim_ids=filtered_claim_ids,
        unsupported_gaps=drafted.unsupported_gaps,
        tone_notes=drafted.tone_notes,
        word_count=word_count,
        retries_used=retries_used,
    )

    all_sections: list[SectionResult] = []
    needs_more_research: list[str] = []
    for i, s in enumerate(current_sections):
        if i == target_index:
            all_sections.append(edited_result)
            needs_more_research.extend(f"{edited_result.section_id}: {gap}" for gap in edited_result.unsupported_gaps)
        else:
            existing = SectionResult(
                section_id=s["section_id"],
                heading=s["heading"],
                body_markdown=s["body_markdown"],
                claim_ids=s.get("claim_ids", []),
                unsupported_gaps=s.get("unsupported_gaps") or [],
                tone_notes=s.get("tone_notes") or "",
                word_count=s.get("word_count") or _word_count(s["body_markdown"]),
                retries_used=s.get("retries_used") or 0,
            )
            all_sections.append(existing)
            needs_more_research.extend(f"{existing.section_id}: {gap}" for gap in existing.unsupported_gaps)

    draft_version = await asyncio.to_thread(repo.get_next_draft_version, input.run_id)
    output = WriterOutput(
        run_id=input.run_id,
        draft_version=draft_version,
        sections=all_sections,
        needs_more_research=needs_more_research,
    )

    await asyncio.to_thread(repo.save_writer_output, output.model_dump())

    logger.info(
        "Edited section_id=%s for run_id=%s (preset=%s, retries_used=%d, new_draft_version=%d)",
        input.section_id,
        input.run_id,
        input.preset.value,
        retries_used,
        draft_version,
    )

    return output
