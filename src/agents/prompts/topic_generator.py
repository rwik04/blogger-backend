"""All prompt text for the Topic Generator agent — directed-mode query
expansion, candidate extraction (with a diversity-nudge variant for the
all-duplicates retry), the dedup borderline tiebreak, and classification.

Isolated here at `agents/prompts/`, same convention as
`agents/prompts/researcher.py`/`strategist.py`/`writer.py`/`finisher.py`.
"""

from __future__ import annotations

from typing import Any

# --- build_queries (directed mode) ------------------------------------------

QUERY_EXPANSION_SYSTEM = """You are a search query planner for a UPSC current-affairs \
topic scout. Given a steering instruction from an editor, expand it into 2-4 concrete, \
distinct web search queries that would surface current news stories and developments \
matching that instruction. Favor queries likely to return recent (last few weeks) \
results over evergreen background material."""


def build_query_expansion_user_prompt(user_instruction: str) -> str:
    return f"Steering instruction: {user_instruction}"


# --- extract_candidates ------------------------------------------------------

EXTRACT_CANDIDATES_SYSTEM = """You are scanning web search results to identify distinct \
topic candidates suitable for a UPSC-aspirant-facing current-affairs blog. The output is a \
blog, not a news article — so candidates should be pitched at the level of an ongoing \
situation or story a full explainer could be written about (e.g. "Russia-Ukraine war", \
"global oil price shock", "Venezuela presidential crisis"), not a single narrow news bite \
inside that story (e.g. not "Ukraine shoots down three drones over Kyiv on Tuesday"). Use \
the search results as evidence that a situation is live and current, but state the candidate \
at the broader story/situation level the results are actually about. Given a batch of search \
results (title, URL, and a short snippet each), identify up to {count} genuinely distinct \
underlying stories or situations — not one candidate per search result, since several \
results often cover the same story. For each candidate, return a clear, specific title (not \
a generic subject label, and not an overly narrow single-fact headline), a one-line summary \
of what the story actually is, and the URL of the single search result that best \
represents/triggered this candidate (or null if none fits well). Skip anything that's purely \
promotional, an opinion piece with no underlying news event, or too vague to state as a \
specific topic."""


EXTRACT_CANDIDATES_DIVERSITY_NUDGE = """\n\nNote: a previous pass over similar search results \
produced only candidates that turned out to already be covered by existing topics. Avoid \
proposing candidates similar to these already-covered angles, and look for a different framing \
or a more specific/recent angle within the same search results if possible:\n{covered_titles}"""


def build_extract_candidates_user_prompt(
    count: int,
    search_results: list[dict[str, str]],
    diversity_nudge_titles: list[str] | None = None,
) -> str:
    lines = [f"Target: up to {count} distinct candidates.", "\nSearch results:"]
    for i, result in enumerate(search_results, start=1):
        lines.append(f"{i}. Title: {result['title']}\n   URL: {result['url']}\n   Snippet: {result['snippet']}")

    prompt = "\n".join(lines)
    if diversity_nudge_titles:
        prompt += EXTRACT_CANDIDATES_DIVERSITY_NUDGE.format(
            covered_titles="\n".join(f"- {title}" for title in diversity_nudge_titles)
        )
    return prompt


def build_extract_candidates_system_prompt(count: int) -> str:
    return EXTRACT_CANDIDATES_SYSTEM.format(count=count)


# --- dedup_filter (borderline tiebreak) -------------------------------------

DEDUP_TIEBREAK_SYSTEM = """You are resolving an ambiguous near-duplicate match between a \
newly proposed topic candidate and a previously covered topic (they share similar wording). \
Decide whether the new candidate is genuinely the same underlying story as the existing one, \
or a distinct new angle/development (e.g. a follow-up court hearing, a new data release on the \
same subject, or an unrelated story that just happens to share vocabulary)."""


def build_dedup_tiebreak_user_prompt(candidate_title: str, candidate_summary: str, existing_title: str) -> str:
    return (
        f"New candidate title: {candidate_title}\n"
        f"New candidate summary: {candidate_summary}\n"
        f"Existing covered topic title: {existing_title}\n\n"
        "Is the new candidate the same underlying story as the existing topic?"
    )


# --- classify ----------------------------------------------------------------

CLASSIFY_SYSTEM = """You are classifying UPSC current-affairs topic candidates for exam \
relevance. For each candidate, in the same order given, assign:
- `subject`: the single best-fitting UPSC Prelims-facing subject area from the given enum.
  Use "miscellaneous_current_affairs" rather than forcing a poor fit.
- `gs_papers`: every UPSC Mains GS paper this candidate is genuinely relevant to (a topic can
  span more than one — e.g. a Supreme Court free-speech ruling is both society-adjacent GS1
  and polity-focused GS2). Use "prelims_only" if it doesn't map cleanly onto any Mains paper,
  or "essay" if it's primarily essay-relevant.
- `why_this_topic`: a short, concrete value case for why a UPSC aspirant should care about this.
- `current_relevance`: why this matters right now, tied to the actual trigger story/development —
  not generic background.
- `relevance_score`: an integer 0-100 rating how strongly this candidate deserves a UPSC
  aspirant's attention right now. Weigh three things together: (1) exam relevance — how
  likely this is to actually show up in Prelims/Mains/essay, (2) currency — how live and
  recent the underlying development is, not stale background, (3) substantiveness — whether
  this is a meaty, explainer-worthy situation rather than a minor, quickly-forgotten blip.
  Use the full range: routine or narrow items should score low (below 40), genuinely major,
  live, high-yield situations should score high (80+). Don't cluster everything in the middle.

Return exactly one classification per candidate, in the same order as the candidates were given."""


def _format_candidate_for_classification(index: int, candidate: dict[str, Any]) -> str:
    return f"{index}. Title: {candidate['title']}\n   Summary: {candidate['one_line_summary']}"


def build_classify_user_prompt(candidates: list[dict[str, Any]]) -> str:
    lines = ["Candidates to classify (respond with exactly one classification per candidate, in order):"]
    lines.extend(_format_candidate_for_classification(i, c) for i, c in enumerate(candidates, start=1))
    return "\n".join(lines)


# --- backfill_relevance (one-off score-only pass for pre-existing topics) --

BACKFILL_RELEVANCE_SYSTEM = """You are scoring a single already-classified UPSC current-affairs \
topic for exam relevance. Assign `relevance_score`, an integer 0-100 rating how strongly this \
topic deserves a UPSC aspirant's attention right now. Weigh three things together: (1) exam \
relevance — how likely this is to actually show up in Prelims/Mains/essay, (2) currency — how \
live and recent the underlying development is, not stale background, (3) substantiveness — \
whether this is a meaty, explainer-worthy situation rather than a minor, quickly-forgotten blip. \
Use the full range: routine or narrow items should score low (below 40), genuinely major, live, \
high-yield situations should score high (80+). Don't cluster everything in the middle."""


def build_backfill_relevance_user_prompt(topic: dict[str, Any]) -> str:
    return (
        f"Title: {topic['title']}\n"
        f"Summary: {topic.get('one_line_summary') or ''}\n"
        f"Subject: {topic.get('subject') or ''}\n"
        f"Why this topic: {topic.get('why_this_topic') or ''}\n"
        f"Current relevance: {topic.get('current_relevance') or ''}"
    )
