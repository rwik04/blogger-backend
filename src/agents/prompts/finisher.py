"""All prompt text for the Finisher agent — system prompts for the two LLM
calls (candidate-question generation, media-prompt generation). The SEO
audit and quiz validation/assembly steps are deterministic and need no
prompts.

Isolated here (at `agents/prompts/`, sibling to each agent's own package),
same reasoning as the other agents' prompt modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.researcher.models import Claim
    from agents.strategist.models import OutlineSection, SeoPlan
    from agents.writer.models import SectionResult

# --- generate_candidate_questions -------------------------------------------

GENERATE_CANDIDATES_SYSTEM = """You write UPSC prelims-style multiple-choice questions from a set of \
pre-researched, verified claims about an article's content.

UPSC prelims MCQs are overwhelmingly statement-based: 2-3 numbered \
statements are presented, and the question asks "Which of the statements \
given above is/are correct?" — you do not write the answer options \
yourself (those are assembled separately); you only write the statements \
themselves, each individually tagged true or false, plus which claim (by \
its ID) each statement is based on.

For each candidate question:
- Write a short `stem` introducing the topic of the statements (e.g. \
"Consider the following statements about the tournament's format:").
- Write 2 or 3 `statements`. Each one is a sentence that reads like an exam \
statement, tagged `is_true` (true or false) and citing the `claim_id` of \
the claim it's based on.
  - TRUE statements must be a faithful paraphrase of their cited claim — \
don't add details the claim doesn't support.
  - FALSE statements must still be clearly related to their cited claim, \
but altered so they're actually wrong — change a number, invert a \
relationship, overstate a qualifier, or swap which entity something \
applies to. A false statement that has nothing to do with the claim it \
cites is a weak question; a false statement that's actually just the true \
claim reworded is a broken one.
  - A well-known tell for a deliberately false statement in real UPSC \
questions is absolute language — words like "always", "never", "only", \
"completely", "must", "entirely", "every time" — use this technique for \
some of your false statements rather than making them obviously wrong.
  - Prefer making 2 or 3 of the statements true rather than 0 or 1 true — \
this matches how real UPSC statement sets are usually composed and how the \
final answer options are structured.
- Do not write duplicate or near-duplicate statements within the same \
question.
- Write a short `explanation` grounded in the cited claim(s), and set \
`related_section_id` to whichever article section the question is drawn \
from.

Generate exactly the requested number of candidate questions."""


def _format_claim(claim: "Claim") -> str:
    flag = " [CONTRADICTED]" if claim.contradicted else ""
    return f"- [{claim.id}]{flag} {claim.text}"


def _format_section(section: "OutlineSection") -> str:
    return f"- [{section.section_id}] {section.heading}"


def build_generate_candidates_user_prompt(
    topic: str,
    audience_tag: str | None,
    outline: list["OutlineSection"],
    claims: list["Claim"],
    candidate_count: int,
) -> str:
    lines = [f"Topic: {topic}"]
    if audience_tag:
        lines.append(f"Audience tag: {audience_tag}")

    lines.append("\nArticle sections (use related_section_id from this list):")
    lines.extend(_format_section(s) for s in outline)

    lines.append(f"\nAvailable claims ({len(claims)} total):")
    lines.extend(_format_claim(c) for c in claims)

    lines.append(f"\nGenerate exactly {candidate_count} candidate questions, spanning multiple sections where possible.")
    return "\n".join(lines)


# --- plan_media --------------------------------------------------------

PLAN_MEDIA_SYSTEM = """You write image-generation prompts and alt text for a blog article's \
media assets — you do not generate images yourself, only the prompt an \
image model would use and accessible alt text for the resulting image.

For the banner (always exactly one): a wide, visually striking prompt \
representing the article's topic as a whole, suitable as the article's \
header image.

For each requested infographic (tied to one article section): a prompt for \
a simple, informative infographic visualizing that section's key point \
(e.g. a diagram, timeline, or comparison relevant to the section's content) \
— not a generic decorative image.

Alt text should be a concise, accurate description of what the image \
depicts, suitable for screen readers — not a repeat of the prompt."""


def build_plan_media_user_prompt(
    topic: str,
    seo_plan: "SeoPlan",
    infographic_sections: list["SectionResult"],
) -> str:
    lines = [
        f"Topic: {topic}",
        f"Primary keyword: {seo_plan.primary_keyword}",
        "\nGenerate 1 banner prompt (section_id: null) plus 1 infographic prompt for each of the following sections:",
    ]
    lines.extend(f"- [{s.section_id}] {s.heading}" for s in infographic_sections)
    return "\n".join(lines)
