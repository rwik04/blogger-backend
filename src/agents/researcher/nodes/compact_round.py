"""Step 5, run per round — the compaction step. RESEARCHER.md §3 step 5,
adapted for the iterative loop: instead of one giant call over every source
at the very end, each round's raw text is condensed into atomic claims plus
short source summaries immediately, merged into the cumulative (compacted)
memory, and the raw text is discarded from state right after this node runs.

This is the node that makes the iterative loop safe on context size — no
matter how many rounds a run takes, the LLM calls after this point
(`reflect_coverage`, and any subsequent round's `compact_round`) only ever
see compacted claims/summaries, never raw page text.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from agents.prompts.researcher import COMPACT_ROUND_SYSTEM, build_compact_round_user_prompt
from agents.researcher.models import Claim, ExtractedClaim, RoundCompaction
from agents.researcher.state import RawSearchHit
from graph.engine import NodeFn
from llm.client import LLMClient


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _merge_claims(existing: list[Claim], new_claims: list[ExtractedClaim]) -> list[Claim]:
    """Merges by normalized-text match: the same claim surfacing again with a
    new supporting source bumps confidence and appends the source id, rather
    than being appended as a duplicate. A simplification vs. embedding-based
    semantic merge — good enough for exact/near-exact repeats across rounds,
    noted as a deferred refinement in the plan.
    """
    by_norm: dict[str, Claim] = {_normalize(c.text): c for c in existing}
    next_id = len(existing) + 1

    for new_claim in new_claims:
        key = _normalize(new_claim.text)
        if key in by_norm:
            current = by_norm[key]
            merged_source_ids = list(dict.fromkeys(current.source_ids + new_claim.source_ids))
            by_norm[key] = current.model_copy(
                update={
                    "source_ids": merged_source_ids,
                    "confidence": "high" if len(merged_source_ids) > 1 else new_claim.confidence,
                    "contradicted": current.contradicted or new_claim.contradicted,
                }
            )
        else:
            by_norm[key] = Claim(
                id=f"claim-{next_id}",
                text=new_claim.text,
                source_ids=new_claim.source_ids,
                confidence=new_claim.confidence,
                contradicted=new_claim.contradicted,
            )
            next_id += 1

    return list(by_norm.values())


def make_compact_round_node(llm_client: LLMClient) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        hits: list[RawSearchHit] = state.get("round_hits", [])
        if not hits:
            return {"round_hits": []}

        messages = [
            {"role": "system", "content": COMPACT_ROUND_SYSTEM},
            {"role": "user", "content": build_compact_round_user_prompt(hits)},
        ]
        result: RoundCompaction = await asyncio.to_thread(llm_client.reason, messages, RoundCompaction)

        claims = _merge_claims(state.get("claims", []), result.claims)

        summaries = dict(state.get("source_summaries", {}))
        for entry in result.source_summaries:
            summaries[entry.source_id] = entry.summary

        return {
            "claims": claims,
            "source_summaries": summaries,
            "round_hits": [],  # raw text discarded here — never crosses into the next round
        }

    return node
