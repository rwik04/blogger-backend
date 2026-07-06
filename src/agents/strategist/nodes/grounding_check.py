"""Step 2 — pure-Python grounding check for the drafted outline's keywords
(STRATEGIST.md §2's "one grounding check, in plain Python, not a library").
Doesn't touch the LLM and doesn't reject anything: it only flags each
outline section's `target_keyword` as `grounded: bool` based on whether it
actually shows up in the same claims/source titles the `draft_plan` prompt
was built from.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from graph.engine import NodeFn

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "a", "an", "the", "of", "for", "and", "or", "in", "on", "to", "with",
    "is", "are", "at", "by", "from", "as", "vs",
}


def _significant_words(phrase: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", phrase.lower())
    return [w for w in words if w not in _STOPWORDS]


def is_grounded(keyword: str, haystack_lower: str) -> bool:
    """Verbatim (case-insensitive) substring match first; falls back to
    every significant word of the phrase appearing individually somewhere
    in the haystack — STRATEGIST.md §2's "near-match" allowance.
    """
    if keyword.lower() in haystack_lower:
        return True

    words = _significant_words(keyword)
    if not words:
        return False
    return all(word in haystack_lower for word in words)


def build_grounding_haystack(claims: list[dict[str, Any]], sources: list[dict[str, Any]]) -> str:
    """The same text the `draft_plan` prompt was built from — claim text
    plus source titles — lowercased once for repeated substring checks.
    """
    parts = [c["text"] for c in claims] + [s["title"] for s in sources]
    return "\n".join(parts).lower()


def check_outline_grounding(
    outline: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Returns a new list of outline-section dicts, each with a `grounded`
    key added/overwritten. Also logs (doesn't fail) a warning if two
    sections share the same non-null `target_keyword` — STRATEGIST.md §8's
    "worth a warning, not a hard failure" edge case.
    """
    haystack = build_grounding_haystack(claims, sources)

    seen_keywords: dict[str, Any] = {}
    grounded_sections: list[dict[str, Any]] = []
    for section in outline:
        keyword = section.get("target_keyword")
        grounded = is_grounded(keyword, haystack) if keyword else False
        grounded_sections.append({**section, "grounded": grounded})

        if keyword:
            prior_section_id = seen_keywords.get(keyword.lower())
            if prior_section_id is not None:
                logger.warning(
                    "Sections %r and %r share the same target_keyword %r",
                    prior_section_id,
                    section.get("section_id"),
                    keyword,
                )
            else:
                seen_keywords[keyword.lower()] = section.get("section_id")

    return grounded_sections


def make_grounding_check_node() -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        drafted_plan = state["drafted_plan"]
        research_brief = state["research_brief"]

        grounded_outline = check_outline_grounding(
            drafted_plan["outline"], research_brief["claims"], research_brief["sources"]
        )
        grounded_count = sum(1 for section in grounded_outline if section["grounded"])
        summary = f"{grounded_count}/{len(grounded_outline)} keywords grounded in research"

        return {
            "drafted_plan": {**drafted_plan, "outline": grounded_outline},
            "_event_summary": summary,
        }

    return node
