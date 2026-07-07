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


def _format_claim(claim: "Claim") -> str:
    flag = " [CONTRADICTED]" if claim.contradicted else ""
    return f"- [{claim.id}]{flag} {claim.text}"


def _format_section(section: "OutlineSection") -> str:
    return f"- [{section.section_id}] {section.heading}"


# --- assess_quiz_relevance --------------------------------------------------

ASSESS_QUIZ_RELEVANCE_SYSTEM = """You decide whether an article's content actually supports a good \
UPSC prelims-style objective quiz, before any quiz is generated.

UPSC prelims MCQs are statement-based and need concrete, checkable facts to \
work: specific numbers, dates, named entities (people/places/organizations/ \
schemes), definitions, categorical classifications, or step-by-step \
processes. A topic built from these can produce statements that are \
unambiguously true or false against the source material.

Some topics genuinely can't support this well, even with a fully accurate, \
well-written article: pieces that are mostly narrative, personal opinion, \
human-interest framing, diplomatic goodwill language ("India lauds...", \
"leaders reaffirmed friendship..."), or general commentary without hard, \
verifiable specifics. Forcing statement-based questions onto this kind of \
content produces either trivial statements or statements that quietly \
overreach what the claims actually support — worse than not having a quiz \
at all.

Look at the topic, the article's section headings, and the actual \
researched claims. Decide `quiz_relevant`: true only if there's enough \
concrete, checkable factual density across the claims (numbers, dates, \
named entities, defined terms, or a clear process/sequence) to write \
several defensible true/false statements without inventing detail beyond \
what's given. Otherwise false.

Write a one-sentence `reason` either way — if false, name what's missing \
(e.g. "mostly diplomatic goodwill language, no concrete figures or named \
mechanisms to test"); if true, name what supports it (e.g. "specific dates, \
named institutions, and numeric figures throughout")."""


def build_assess_quiz_relevance_user_prompt(
    topic: str,
    audience_tag: str | None,
    outline: list["OutlineSection"],
    claims: list["Claim"],
) -> str:
    lines = [f"Topic: {topic}"]
    if audience_tag:
        lines.append(f"Audience tag: {audience_tag}")

    lines.append("\nArticle sections:")
    lines.extend(_format_section(s) for s in outline)

    lines.append(f"\nResearched claims ({len(claims)} total):")
    lines.extend(_format_claim(c) for c in claims)

    return "\n".join(lines)


# --- generate_candidate_questions -------------------------------------------

GENERATE_CANDIDATES_SYSTEM = """You write exam-style multiple-choice questions from a set of \
pre-researched, verified claims about an article's content.

Write a MIX of two question types across the candidates you generate — do \
not make every question the same type. Pick whichever type actually fits \
each claim best:

- `"direct"` — a plain, single-answer question with independent answer \
choices, e.g. "How many teams will compete in the 2026 FIFA World Cup?" \
with choices like "32", "40", "48", "64". Use this for a claim that's a \
single checkable fact: a count, a date, a named entity, a rate, a location. \
Most claims are this shape, so most of your questions should be too.
- `"statement_based"` — the classic UPSC-prelims format: 2-3 numbered \
statements, and the question asks "Which of the statements given above \
is/are correct?" (the answer options for this type are combination-style \
like "1 and 3 only" and are assembled separately, not written by you). Use \
this only when a claim actually involves multiple related sub-facts worth \
testing together (e.g. several details about one scheme, or a \
comparison) — don't force two unrelated claims into fake "statements" just \
to use this format.

For every candidate, regardless of type, set `question_type`, write a short \
`explanation` grounded in the cited claim(s), and set `related_section_id` \
to whichever article section the question is drawn from. Both `statements` \
and `answer_options` are required fields on every candidate — populate \
only the one matching `question_type` and leave the other as an empty list.

For a `"direct"` question:
- Write `stem` as the actual question, ending in "?" — not a lead-in \
sentence like "Consider the following statements".
- Write 3 or 4 `answer_options`. Exactly one has `is_correct: true`; it \
must be a faithful, verbatim-or-near-verbatim fact from its cited \
`claim_id` — don't invent a number or name the claims don't support.
- The other options are plausible distractors: adjacent numbers, similar \
names, or common misconceptions about the same topic. They should read as \
genuinely tempting wrong answers, not obviously silly ones. Distractors \
don't need to cite a claim (`claim_id: null` is fine for an invented \
plausible-sounding wrong answer) — only the correct option must be grounded.
- Do not write duplicate or near-duplicate answer choices.

For a `"statement_based"` question:
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

Generate exactly the requested number of candidate questions."""


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

    lines.append(
        f"\nGenerate exactly {candidate_count} candidate questions, spanning multiple sections where "
        "possible and mixing both question types — lean towards \"direct\" questions for single-fact "
        "claims, and reserve \"statement_based\" for claims that genuinely involve multiple related "
        "sub-facts."
    )
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
