"""Shared mutable state threaded through every node in the Researcher graph.

Deliberately absent: any field holding raw scraped page text across a node
boundary into a later round. Raw text lives only inside `search_subquery`/
`selective_scrape`'s local results and the `compact_round` call that
immediately consumes and discards it — see RESEARCHER-agent plan, "Why
iterative, and why compaction is the crux".
"""

from __future__ import annotations

from typing import Any, TypedDict

from agents.researcher.models import Claim, Source


class RawSearchHit(TypedDict):
    """One search result, ephemeral within a single round — never persisted
    into cumulative state as-is."""

    source_id: str
    url: str
    title: str
    domain: str
    content: str  # inline text from the search tool; may be truncated/empty
    needs_scrape: bool


class ResearcherState(TypedDict, total=False):
    # input
    run_id: str
    topic: str
    audience_tag: str | None

    # loop control
    iteration: int
    max_iterations: int

    # queries
    sub_queries_asked: list[str]        # cumulative across all rounds
    sub_queries_this_round: list[str]

    # this-round scratch (ephemeral — overwritten/cleared each round)
    round_search_results: list[list[RawSearchHit]]  # one list per sub-query, from the fan-out
    round_hits: list[RawSearchHit]                  # flattened + deduped + filtered this round
    round_summary_note: str | None                  # e.g. "kept 9 of 14 candidates"

    # cumulative compacted memory (the only thing that survives across rounds)
    sources: list[Source]
    claims: list[Claim]
    source_summaries: dict[str, str]  # source_id -> short summary

    # reflection
    reflect_decision: str | None
    reflect_reasoning: str | None

    # terminal
    status: str
    error: str | None
    brief: dict[str, Any] | None
