"""All prompt text for the Researcher agent — system prompts and the
functions that render them alongside per-call state into user messages.

Isolated here (at `agents/prompts/`, sibling to each agent's own package,
not nested inside `agents/researcher/`) so prompt tuning is a one-directory
job regardless of which agent it's for, and so node modules stay focused on
orchestration (calling the LLM/MCP client, shaping state) rather than prompt
copy. As Strategist/Writer/etc. get built, their prompts go in
`agents/prompts/strategist.py`, `agents/prompts/writer.py`, and so on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.researcher.models import Claim
    from agents.researcher.state import RawSearchHit

# --- plan_queries ------------------------------------------------------------

PLAN_QUERIES_SYSTEM = """You are a research planner for a blog-writing pipeline. \
Given a topic (and optionally an audience tag), produce 4-6 sub-questions \
that together cover distinct angles: definition/background, recent \
developments, data/statistics, and competing viewpoints. \
If the audience tag is "UPSC", include one sub-question framed around \
exam relevance. Diversity of angles matters more than volume — avoid \
sub-questions that are just rephrasings of each other."""


def build_plan_queries_user_prompt(topic: str, audience_tag: str | None) -> str:
    prompt = f"Topic: {topic}"
    if audience_tag:
        prompt += f"\nAudience tag: {audience_tag}"
    return prompt


# --- compact_round -------------------------------------------------------

COMPACT_ROUND_SYSTEM = """You are extracting atomic, source-attributed claims from \
web research for a blog research brief. For each provided source, produce:

1. Atomic claims (one fact/assertion per claim), each tagged with the \
source_id(s) that support it — a claim can cite multiple sources if they agree.
2. confidence: "high" if multiple independent sources agree, "medium" if \
only one credible source supports it, "low" if weakly supported.
3. contradicted: true if two sources disagree on this specific point.
4. A short 2-3 sentence summary for each source.

Only use facts present in the provided source text — do not invent or infer \
facts beyond what's written."""

COMPACT_ROUND_MAX_CONTENT_CHARS_PER_SOURCE = 8000


def build_compact_round_user_prompt(hits: list["RawSearchHit"]) -> str:
    blocks = []
    for hit in hits:
        content = hit["content"][:COMPACT_ROUND_MAX_CONTENT_CHARS_PER_SOURCE]
        blocks.append(f"[source_id={hit['source_id']}] {hit['title']} ({hit['url']})\n{content}")
    return "\n\n---\n\n".join(blocks)


# --- reflect_coverage ------------------------------------------------------

REFLECT_COVERAGE_SYSTEM = """You are deciding whether a research brief has enough \
coverage to hand off to a blog writer, or whether another round of targeted \
search is needed.

Decide "finalize" if the sub-questions asked are reasonably answered, there \
is a healthy mix of confidence levels across claims, and any contradictions \
are clearly flagged rather than left ambiguous.

Decide "continue" if there is a clear gap — an angle with zero or very thin \
claim coverage, or an unresolved contradiction worth chasing with another \
source. If continuing, propose 2-4 new, specific sub-questions that target \
the gaps directly. Do not repeat sub-questions already asked."""


def _format_claim(claim: "Claim") -> str:
    flag = " [CONTRADICTED]" if claim.contradicted else ""
    return f"- ({claim.confidence}){flag} {claim.text}"


def build_reflect_coverage_user_prompt(state: dict[str, Any]) -> str:
    lines = [f"Topic: {state['topic']}"]
    if state.get("audience_tag"):
        lines.append(f"Audience tag: {state['audience_tag']}")

    lines.append("\nSub-questions already asked:")
    lines.extend(f"- {q}" for q in state.get("sub_queries_asked", []))

    claims: list["Claim"] = state.get("claims", [])
    lines.append(f"\nClaims gathered so far ({len(claims)} total):")
    lines.extend(_format_claim(c) for c in claims)

    return "\n".join(lines)
