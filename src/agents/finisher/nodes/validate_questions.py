"""Step 2 of the quiz pipeline — deterministic grounding validation
(FINISHER.md §2 step 2), no LLM call. Reuses the same "significant words"
overlap discipline as the Strategist's keyword grounding check
(`agents.strategist.nodes.grounding_check`) rather than reinventing a
second grounding heuristic.

Failing candidates are dropped outright, not repaired — per FINISHER.md §2:
repairing a single statement inside an already-assembled multi-statement
question risks fixing one statement while leaving the option combination
stale.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.strategist.nodes.grounding_check import _significant_words
from graph.engine import NodeFn

logger = logging.getLogger(__name__)

_TRUE_MIN_OVERLAP = 0.8
"""A `is_true` statement must have (nearly) all of its significant words
present in the cited claim's text — a near-paraphrase, mirroring
`grounding_check.is_grounded`'s "all significant words present" rule."""

_FALSE_MIN_OVERLAP = 0.3
"""A `is_false` statement must still share some vocabulary with its cited
claim — an unrelated false statement is a weak question (FINISHER.md §2)."""

_FALSE_MAX_OVERLAP = 0.75
"""...but must not be a near-verbatim match of the claim either — that
would mean it's actually true and mistagged."""

_DUPLICATE_OVERLAP = 0.85
_MIN_TRUE_FOR_THREE_STATEMENTS = 2
"""Only 3-statement true/false patterns with >=2 true statements have an
entry in `assemble_questions`'s option lookup table — checked here too so
these candidates are dropped (and logged) at validation time rather than
silently disappearing during assembly."""


_MIN_ANSWER_OPTIONS = 3
_MAX_ANSWER_OPTIONS = 4
"""A `"direct"` question needs at least 3 answer choices to be a real MCQ,
and the assembled quiz UI shows a/b/c/d, so cap at 4 to match."""


def _statement_words(text: str) -> list[str]:
    return _significant_words(text)


def _overlap_ratio(words: list[str], reference_words: set[str]) -> float:
    if not words:
        return 0.0
    matched = sum(1 for word in words if word in reference_words)
    return matched / len(words)


def _are_near_duplicates(words_a: list[str], words_b: list[str]) -> bool:
    if not words_a or not words_b:
        return False
    set_a, set_b = set(words_a), set(words_b)
    return len(set_a & set_b) / len(set_a | set_b) >= _DUPLICATE_OVERLAP


def _validate_statement_based(candidate: dict[str, Any], claims_by_id: dict[str, str]) -> str | None:
    statements = candidate["statements"]

    if len(statements) not in (2, 3):
        return f"has {len(statements)} statement(s); only 2 or 3-statement questions are supported"

    statement_words: list[list[str]] = []
    for index, statement in enumerate(statements):
        claim_text = claims_by_id.get(statement["claim_id"])
        if claim_text is None:
            return f"statement {index + 1} cites unknown claim_id {statement['claim_id']!r}"

        words = _statement_words(statement["text"])
        overlap = _overlap_ratio(words, set(_statement_words(claim_text)))
        statement_words.append(words)

        if statement["is_true"]:
            if overlap < _TRUE_MIN_OVERLAP:
                return (
                    f"statement {index + 1} tagged true doesn't closely match its cited claim "
                    f"(overlap={overlap:.2f}, need>={_TRUE_MIN_OVERLAP})"
                )
        else:
            if overlap < _FALSE_MIN_OVERLAP:
                return f"statement {index + 1} tagged false is unrelated to its cited claim (overlap={overlap:.2f})"
            if overlap >= _FALSE_MAX_OVERLAP:
                return (
                    f"statement {index + 1} tagged false is a near-verbatim match of its cited claim "
                    f"(overlap={overlap:.2f}); looks mistagged"
                )

    for i in range(len(statement_words)):
        for j in range(i + 1, len(statement_words)):
            if _are_near_duplicates(statement_words[i], statement_words[j]):
                return f"statements {i + 1} and {j + 1} are near-duplicates of each other"

    if len(statements) == 3:
        true_count = sum(1 for s in statements if s["is_true"])
        if true_count < _MIN_TRUE_FOR_THREE_STATEMENTS:
            return (
                f"3-statement question has only {true_count} true statement(s); "
                f"at least {_MIN_TRUE_FOR_THREE_STATEMENTS} required to map to a combination option"
            )

    return None


def _validate_direct(candidate: dict[str, Any], claims_by_id: dict[str, str]) -> str | None:
    options = candidate["answer_options"]

    if not (_MIN_ANSWER_OPTIONS <= len(options) <= _MAX_ANSWER_OPTIONS):
        return (
            f"has {len(options)} answer option(s); need between "
            f"{_MIN_ANSWER_OPTIONS} and {_MAX_ANSWER_OPTIONS}"
        )

    correct = [o for o in options if o["is_correct"]]
    if len(correct) != 1:
        return f"has {len(correct)} option(s) tagged correct; exactly 1 is required"

    correct_option = correct[0]
    claim_text = claims_by_id.get(correct_option["claim_id"])
    if claim_text is None:
        return f"correct option cites unknown claim_id {correct_option['claim_id']!r}"

    correct_words = _statement_words(correct_option["text"])
    overlap = _overlap_ratio(correct_words, set(_statement_words(claim_text)))
    if overlap < _TRUE_MIN_OVERLAP:
        return f"correct option doesn't closely match its cited claim (overlap={overlap:.2f}, need>={_TRUE_MIN_OVERLAP})"

    option_words = [_statement_words(o["text"]) for o in options]
    for i in range(len(option_words)):
        for j in range(i + 1, len(option_words)):
            if _are_near_duplicates(option_words[i], option_words[j]):
                return f"options {i + 1} and {j + 1} are near-duplicates of each other"

    return None


def validate_candidate(candidate: dict[str, Any], claims_by_id: dict[str, str]) -> str | None:
    """Returns a failure reason string, or `None` if the candidate passes
    every check and should survive to option assembly. Dispatches on
    `question_type` — `"statement_based"` reuses the original
    statement/combination-option checks; `"direct"` checks the single
    correct answer's grounding plus basic option hygiene.
    """
    if candidate["question_type"] == "direct":
        return _validate_direct(candidate, claims_by_id)
    return _validate_statement_based(candidate, claims_by_id)


def make_validate_questions_node() -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        candidates = state.get("candidate_questions", [])
        claims_by_id = {c["id"]: c["text"] for c in state["research_brief"]["claims"]}

        validated: list[dict[str, Any]] = []
        for candidate in candidates:
            reason = validate_candidate(candidate, claims_by_id)
            if reason is None:
                validated.append(candidate)
            else:
                logger.info("Dropping candidate question (stem=%r): %s", candidate.get("stem"), reason)

        summary = f"{len(validated)}/{len(candidates)} candidate(s) passed grounding validation"
        return {"validated_questions": validated, "_event_summary": summary}

    return node
