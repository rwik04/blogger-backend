"""Deterministic SEO audit — FINISHER.md §3 — no LLM call. Runs against the
Writer's assembled sections and the Strategist's `SeoPlan`/outline:
keyword density, a heading-hierarchy sanity check, meta description length,
and internal-link suggestions from shared outline keywords (reusing the
Strategist's `_significant_words` word-overlap helper rather than a new
embedding step, per §3's explicit instruction).
"""

from __future__ import annotations

import re
from typing import Any

from agents.strategist.nodes.grounding_check import _significant_words
from graph.engine import NodeFn

_DENSITY_LOW = 0.005
_DENSITY_HIGH = 0.03
_META_MIN_LEN = 120
_META_MAX_LEN = 160
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")


def _word_count(text: str) -> int:
    return len(text.split())


def compute_keyword_density(body_text: str, keywords: list[str]) -> dict[str, float]:
    """Simple word-count-ratio density per keyword (occurrence count over
    total word count) — flagging (outside ~0.5%-3%) is left to callers
    reading this dict; FINISHER.md's `SeoAudit` contract has no separate
    "flagged" field.
    """
    total_words = _word_count(body_text) or 1
    lowered = body_text.lower()
    return {keyword: round(lowered.count(keyword.lower()) / total_words, 4) for keyword in keywords}


def check_headings(sections: list[dict[str, Any]], final_title: str) -> list[str]:
    """Section headings are rendered externally as H2 from `section.heading`
    — any markdown heading syntax found inside `body_markdown` itself is a
    stray header. `final_title` stands in for the page's one H1.
    """
    issues: list[str] = []
    for section in sections:
        for raw_line in section["body_markdown"].splitlines():
            match = _HEADING_RE.match(raw_line.strip())
            if not match:
                continue
            level = len(match.group(1))
            snippet = match.group(2).strip()
            if level == 1:
                issues.append(
                    f"Section '{section['section_id']}' contains a stray H1 ('{snippet}') in its body; "
                    f"'{final_title}' should be the page's only H1."
                )
            else:
                issues.append(
                    f"Section '{section['section_id']}' contains a stray H{level} header ('{snippet}') in its "
                    "body; section headings should be set once as H2 via the section's own heading, not "
                    "embedded in body_markdown."
                )
    return issues


def check_meta_description(meta_description: str) -> bool:
    return _META_MIN_LEN <= len(meta_description) <= _META_MAX_LEN


def suggest_internal_links(outline: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Sections whose `target_keyword`s share significant words get
    suggested as link pairs — no embeddings, per FINISHER.md §3.
    """
    keyworded = [s for s in outline if s.get("target_keyword")]
    suggestions: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, source in enumerate(keyworded):
        source_words = set(_significant_words(source["target_keyword"]))
        for target in keyworded[i + 1 :]:
            if source["section_id"] == target["section_id"]:
                continue
            target_words = set(_significant_words(target["target_keyword"]))
            if not (source_words & target_words):
                continue
            pair_key = tuple(sorted((source["section_id"], target["section_id"])))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            suggestions.append(
                {
                    "from_section": source["section_id"],
                    "to_section": target["section_id"],
                    "anchor_text": target["target_keyword"],
                }
            )
    return suggestions


def make_audit_seo_node() -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        sections = state["writer_output"]["sections"]
        seo_plan = state["strategist_output"]["seo_plan"]
        outline = state["strategist_output"]["outline"]
        final_title = seo_plan["meta_title"]

        body_text = "\n\n".join(s["body_markdown"] for s in sections)
        keywords = [seo_plan["primary_keyword"], *seo_plan["secondary_keywords"]]
        keyword_density = compute_keyword_density(body_text, keywords)

        heading_issues = check_headings(sections, final_title)
        meta_ok = check_meta_description(seo_plan["meta_description"])
        internal_links = suggest_internal_links(outline)

        seo_audit = {
            "keyword_density": keyword_density,
            "heading_issues": heading_issues,
            "meta_description_ok": meta_ok,
            "internal_link_suggestions": internal_links,
        }

        flagged = sum(1 for ratio in keyword_density.values() if ratio < _DENSITY_LOW or ratio > _DENSITY_HIGH)
        summary = (
            f"{len(keyword_density)} keyword(s) measured ({flagged} out of density range), "
            f"{len(heading_issues)} heading issue(s), meta description {'OK' if meta_ok else 'out of range'}, "
            f"{len(internal_links)} internal link(s) suggested"
        )
        return {"seo_audit": seo_audit, "_event_summary": summary}

    return node
