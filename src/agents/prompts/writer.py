"""All prompt text for the Writer agent — one system prompt for the
per-section draft+fact-check+humanize LLM call, plus the two follow-up
repair prompts used for the gap-retry and length-retry loops (WRITER.md §2,
§8).

Isolated here (at `agents/prompts/`, sibling to each agent's own package),
same reasoning as `agents/prompts/researcher.py` and `agents/prompts/strategist.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.researcher.models import Claim
    from agents.strategist.models import OutlineSection

# --- write_section ------------------------------------------------------

WRITE_SECTION_SYSTEM = """You are a blog writer producing one section at a time for a \
longer article, given a fixed outline and a set of pre-researched claims. \
For the requested section only, do three things, in order, within your own \
reasoning before responding:

1. DRAFT: Write the section's body in markdown, addressing its heading and \
target keyword, consistent with the outline and with what has already been \
written earlier in the article (given to you as "draft so far") — don't \
repeat points already made, and don't contradict earlier sections.

2. SELF-FACT-CHECK: Check every factual statement you just wrote against the \
supplied claims. Keep only statements that are directly supported by at \
least one claim. If you wrote something you can't verify against the \
claims, either remove it or rephrase the sentence to drop the unverifiable \
detail — do not delete the whole section over one unverifiable detail. List \
any factual gaps you wanted to cover but couldn't verify as `unsupported_gaps` \
(short phrases, empty list if none).

3. HUMANIZE: Rewrite the checked draft for natural tone. Vary sentence \
length. Don't open the section by restating its heading verbatim. Avoid \
stock AI transitions and filler phrases like "in today's world", "it's \
important to note", "in conclusion", "delve into". Report what you changed \
for tone as a short `tone_notes` string (e.g. "shortened opening sentence, \
removed a stock transition").

Formatting: if this section's heading is about a set of distinct measures, \
steps, initiatives, or developments (rather than a single continuous \
narrative), structure the body as a markdown numbered list — one entry per \
distinct point, each starting with a short bold label (e.g. "1. \
**Strengthening the National Investigation Agency (NIA)** — ...") followed \
by 1-3 sentences of supported detail. Otherwise write normal prose \
paragraphs; don't force a list onto a section that's naturally narrative.

Also return `claim_ids`: the IDs of every claim from the supplied list that \
you actually used and verified the section's content against.

Return only the section's own body — not the heading as a markdown title \
(the heading is rendered separately), and not any other section's content."""


def _format_claim(claim: "Claim") -> str:
    return f"- [{claim.id}] ({claim.confidence}) {claim.text}"


def _format_outline_entry(section: "OutlineSection", is_current: bool) -> str:
    marker = " <- write this section now" if is_current else ""
    keyword = f" (target keyword: {section.target_keyword})" if section.target_keyword else ""
    return f"- [{section.order_index}] {section.heading}{keyword}{marker}"


def build_write_section_user_prompt(
    topic: str,
    audience_tag: str | None,
    outline: list["OutlineSection"],
    claims: list["Claim"],
    draft_so_far: str,
    section: "OutlineSection",
) -> str:
    lines = [f"Topic: {topic}"]
    if audience_tag:
        lines.append(f"Audience tag: {audience_tag}")

    lines.append("\nFull article outline (for context — write only the marked section):")
    lines.extend(_format_outline_entry(s, is_current=s.section_id == section.section_id) for s in outline)

    lines.append(f"\nAvailable claims ({len(claims)} total, cite only what you use):")
    lines.extend(_format_claim(c) for c in claims)

    lines.append("\nDraft so far (previously written sections, may be empty if this is the first section):")
    lines.append(draft_so_far if draft_so_far.strip() else "(nothing written yet)")

    lines.append(f"\nNow write the section: \"{section.heading}\" (section_id={section.section_id}).")
    return "\n".join(lines)


def build_gap_repair_prompt(unsupported_gaps: list[str]) -> str:
    """Follow-up user message for a gap-retry (up to 2 per section,
    WRITER.md §2/§8) — asks the model to rework around the specific
    unverifiable details rather than restarting from scratch.
    """
    gaps = "; ".join(unsupported_gaps)
    return (
        f"Your draft still relies on details that aren't verifiable against the supplied claims: {gaps}. "
        "Rework the section to either drop these details or rephrase around them so every remaining "
        "statement is supported. Return the complete corrected section in the same JSON shape as before."
    )


def build_length_repair_prompt(min_words: int, actual_words: int) -> str:
    """Follow-up user message for the separate length-retry budget
    (WRITER.md §8 — one retry, independent of the gap-retry count).
    """
    return (
        f"Your draft for this section is only about {actual_words} words, below the {min_words}-word minimum. "
        "Expand it with more supported detail from the available claims (do not pad with filler or repeat "
        "earlier sections) and return the complete corrected section in the same JSON shape as before."
    )


# --- edit_section ---------------------------------------------------------

EDIT_SECTION_SYSTEM = """You are rewriting a single section of an already-published blog article, \
given the fixed outline, the full set of pre-researched claims, the rest of the article for context, \
the section's current text, and a specific rewrite instruction. Do three things, in order, within your \
own reasoning before responding:

1. REWRITE: Rewrite the section's body in markdown following the rewrite instruction, staying consistent \
with the outline and with the rest of the article (given to you as "draft so far") — don't repeat points \
already made elsewhere, and don't contradict other sections.

2. SELF-FACT-CHECK: Check every factual statement in your rewrite against the supplied claims. Keep only \
statements directly supported by at least one claim. If you wrote something you can't verify, either \
remove it or rephrase around it — do not delete the whole section over one unverifiable detail. List any \
factual gaps you wanted to cover but couldn't verify as `unsupported_gaps` (short phrases, empty list if \
none).

3. HUMANIZE: Ensure natural tone, varied sentence length, no stock AI transitions or filler phrases. \
Report what you changed for tone as a short `tone_notes` string.

Also return `claim_ids`: the IDs of every claim from the supplied list that you actually used and \
verified the rewritten section's content against.

Return only the section's own body — not the heading as a markdown title, and not any other section's \
content."""


EDIT_PRESET_INSTRUCTIONS: dict[str, str] = {
    "more_engaging": (
        "Make this section more engaging: add a stronger hook, vary sentence rhythm, and use more vivid, "
        "concrete language while keeping every claim factually supported."
    ),
    "more_formal": (
        "Make this section more formal: use precise, neutral language, avoid contractions and casual "
        "phrasing, and tighten the structure — while keeping the same factual content."
    ),
    "more_comprehensive": (
        "Make this section more comprehensive: cover additional supported detail from the available "
        "claims that isn't already used elsewhere in the article, without padding or repeating other "
        "sections."
    ),
}


def build_edit_section_user_prompt(
    topic: str,
    audience_tag: str | None,
    outline: list["OutlineSection"],
    claims: list["Claim"],
    draft_so_far: str,
    section: "OutlineSection",
    current_body_markdown: str,
    instruction: str,
) -> str:
    lines = [f"Topic: {topic}"]
    if audience_tag:
        lines.append(f"Audience tag: {audience_tag}")

    lines.append("\nFull article outline (for context — rewrite only the marked section):")
    lines.extend(_format_outline_entry(s, is_current=s.section_id == section.section_id) for s in outline)

    lines.append(f"\nAvailable claims ({len(claims)} total, cite only what you use):")
    lines.extend(_format_claim(c) for c in claims)

    lines.append("\nDraft so far (every other current section of the article, in order):")
    lines.append(draft_so_far if draft_so_far.strip() else "(no other sections)")

    lines.append(f"\nCurrent text of the section to rewrite (\"{section.heading}\", section_id={section.section_id}):")
    lines.append(current_body_markdown)

    lines.append(f"\nRewrite instruction: {instruction}")
    return "\n".join(lines)
