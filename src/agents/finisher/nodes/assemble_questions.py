"""Steps 3-4 of the quiz pipeline — deterministic option assembly and final
selection (FINISHER.md §2 steps 3-4), no LLM call.

Option assembly is a fixed lookup, not free-form generation: this makes
FINISHER.md §8's flagged risk ("derived correct option matches a
distractor") structurally impossible, since the distractors are always
exactly "the other 3 entries in the same lookup table" — they can never
collide with the correct option by construction.
"""

from __future__ import annotations

import random
import uuid
from typing import Any

from agents.finisher.models import MCQOption, MCQStatement, UpscStyleQuestion
from graph.engine import NodeFn

_TARGET_QUESTION_COUNT = 4
_MIN_QUESTION_COUNT = 3

_TWO_STATEMENT_OPTIONS: dict[tuple[bool, bool], str] = {
    (True, False): "1 only",
    (False, True): "2 only",
    (True, True): "Both 1 and 2",
    (False, False): "Neither 1 nor 2",
}

_THREE_STATEMENT_OPTIONS: dict[tuple[bool, bool, bool], str] = {
    # Only patterns with >=2 true statements get a canonical option, matching
    # FINISHER.md §1's own 4-option example — a pattern with 0-1 true
    # statements has no entry and is dropped (already filtered upstream in
    # `validate_questions`, checked again here for safety).
    (True, True, False): "1 and 2 only",
    (False, True, True): "2 and 3 only",
    (True, False, True): "1 and 3 only",
    (True, True, True): "1, 2 and 3",
}

_OPTION_LABELS = ["a", "b", "c", "d"]


def _option_table(statement_count: int) -> dict[tuple[bool, ...], str] | None:
    if statement_count == 2:
        return _TWO_STATEMENT_OPTIONS
    if statement_count == 3:
        return _THREE_STATEMENT_OPTIONS
    return None


def assemble_question(candidate: dict[str, Any]) -> UpscStyleQuestion | None:
    """Returns the assembled `UpscStyleQuestion`, or `None` if the
    candidate's true/false pattern has no entry in the lookup table.
    Distractors are simply the lookup table's other 3 values — by
    construction they can never collide with the correct option. Labels
    (a/b/c/d) are shuffled per question for variety.
    """
    statements = candidate["statements"]
    table = _option_table(len(statements))
    if table is None:
        return None

    pattern = tuple(bool(s["is_true"]) for s in statements)
    correct_text = table.get(pattern)
    if correct_text is None:
        return None

    option_texts = list(table.values())
    shuffled_labels = _OPTION_LABELS[: len(option_texts)].copy()
    random.shuffle(shuffled_labels)

    options = [MCQOption(label=label, text=text) for label, text in zip(shuffled_labels, option_texts)]
    correct_label = next(opt.label for opt in options if opt.text == correct_text)
    options.sort(key=lambda opt: opt.label)

    return UpscStyleQuestion(
        question_id=str(uuid.uuid4()),
        stem=candidate["stem"],
        statements=[MCQStatement.model_validate(s) for s in statements],
        options=options,
        correct_option=correct_label,
        explanation=candidate["explanation"],
        related_section_id=candidate["related_section_id"],
    )


def select_questions(
    assembled: list[UpscStyleQuestion],
    target_count: int = _TARGET_QUESTION_COUNT,
) -> list[UpscStyleQuestion]:
    """Prefers one question per distinct `related_section_id` up to
    `target_count`; if that doesn't reach the 3-question minimum, tops up
    with the next-best remaining candidates even if a section repeats
    (FINISHER.md §10's "only 2 sections have enough density" edge case).
    """
    selected: list[UpscStyleQuestion] = []
    used_sections: set[str] = set()
    remaining: list[UpscStyleQuestion] = []

    for question in assembled:
        if len(selected) < target_count and question.related_section_id not in used_sections:
            selected.append(question)
            used_sections.add(question.related_section_id)
        else:
            remaining.append(question)

    for question in remaining:
        if len(selected) >= target_count:
            break
        selected.append(question)

    return selected


def make_assemble_questions_node(target_question_count: int = _TARGET_QUESTION_COUNT) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        validated = state.get("validated_questions", [])

        assembled = [q for q in (assemble_question(c) for c in validated) if q is not None]
        selected = select_questions(assembled, target_question_count)

        quality_flags = list(state.get("quality_flags", []))
        if len(selected) < _MIN_QUESTION_COUNT:
            quality_flags.append(
                f"Only {len(selected)} quiz question(s) survived validation/assembly "
                f"(minimum {_MIN_QUESTION_COUNT}) — the draft's sections may lack enough checkable "
                "factual density; consider routing back to the Writer for more concrete detail."
            )

        section_count = len({q.related_section_id for q in selected})
        summary = f"{len(assembled)} assembled, {len(selected)} selected across {section_count} section(s)"

        return {
            "questions": [q.model_dump() for q in selected],
            "quality_flags": quality_flags,
            "_event_summary": summary,
        }

    return node
