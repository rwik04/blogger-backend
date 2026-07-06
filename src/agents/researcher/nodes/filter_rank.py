"""Step 3 — filter + rank. RESEARCHER.md §3 step 3.

Dedupes by normalized URL against sources already collected in *any* prior
round (not just this one), drops a domain blocklist, upweights authoritative
domains for UPSC-audience runs, and caps how many *new* sources one round can
contribute so the running total doesn't balloon across an iterative run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents.researcher.models import Source
from agents.researcher.state import RawSearchHit
from graph.engine import NodeFn

_BLOCKLIST_DOMAINS = {
    "pinterest.com",
    "quora.com",
    "answers.com",
}
_UPSC_PREFERRED_SUFFIXES = (".gov", ".gov.in", ".edu", "pib.gov.in", "prsindia.org")
_MAX_NEW_SOURCES_PER_ROUND = 10


def _is_upsc_preferred(domain: str) -> bool:
    return any(domain.endswith(suffix) for suffix in _UPSC_PREFERRED_SUFFIXES)


def make_filter_rank_node() -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        existing_sources: list[Source] = state.get("sources", [])
        existing_urls = {s.url for s in existing_sources}

        seen_this_round: set[str] = set()
        candidates: list[RawSearchHit] = []
        for round_result in state.get("round_search_results", []):
            for hit in round_result.get("hits", []):
                url = hit["url"]
                if url in existing_urls or url in seen_this_round:
                    continue
                if hit["domain"] in _BLOCKLIST_DOMAINS:
                    continue
                seen_this_round.add(url)
                candidates.append(hit)

        if state.get("audience_tag") == "UPSC":
            candidates.sort(key=lambda h: 0 if _is_upsc_preferred(h["domain"]) else 1)

        kept = candidates[:_MAX_NEW_SOURCES_PER_ROUND]

        now = datetime.now(timezone.utc).isoformat()
        new_sources = [
            Source(id=h["source_id"], url=h["url"], title=h["title"], domain=h["domain"], retrieved_at=now)
            for h in kept
        ]

        summary = f"Kept {len(kept)} of {len(candidates)} candidate sources this round"
        return {
            "round_hits": kept,
            "sources": existing_sources + new_sources,
            "round_summary_note": summary,
            "_event_summary": summary,
        }

    return node
