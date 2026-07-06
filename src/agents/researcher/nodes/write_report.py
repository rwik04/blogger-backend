"""Step after `finalize_brief` — synthesizes the compacted claims into a
long-form narrative report with inline `[n]` citation markers and a trailing
Sources section.

Citation numbers are assigned by us, not the LLM: the LLM only ever sees
claims pre-tagged with their marker (e.g. `[1]` or `[1][2]`) and is
instructed to preserve them verbatim, and we build the final Sources list
ourselves from the same numbering. This guarantees every `[n]` in the report
resolves to the correct URL — it's never left to the model to get citation
bookkeeping right.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.prompts.researcher import WRITE_REPORT_SYSTEM, build_write_report_user_prompt
from graph.engine import NodeFn
from llm.client import LLMClient


def _assign_citation_numbers(sources: list[dict[str, Any]]) -> dict[str, int]:
    """1-indexed citation number per source, in source-list order (i.e.
    discovery order) — fixed here so it can't drift from the Sources section.
    """
    return {source["id"]: i + 1 for i, source in enumerate(sources)}


def _claim_citation_marker(claim: dict[str, Any], citation_numbers: dict[str, int]) -> str:
    numbers = sorted({citation_numbers[sid] for sid in claim["source_ids"] if sid in citation_numbers})
    return "".join(f"[{n}]" for n in numbers)


def _build_sources_section(sources: list[dict[str, Any]], citation_numbers: dict[str, int]) -> str:
    lines = ["## Sources"]
    ordered = sorted(sources, key=lambda s: citation_numbers[s["id"]])
    for source in ordered:
        n = citation_numbers[source["id"]]
        lines.append(f"{n}. [{source['title']}]({source['url']}) — {source['domain']}")
    return "\n".join(lines)


def make_write_report_node(llm_client: LLMClient) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        brief: dict[str, Any] = state["brief"]
        sources: list[dict[str, Any]] = brief["sources"]
        claims: list[dict[str, Any]] = brief["claims"]

        citation_numbers = _assign_citation_numbers(sources)
        cited_claims = [
            {**claim, "citation_marker": _claim_citation_marker(claim, citation_numbers)} for claim in claims
        ]

        messages = [
            {"role": "system", "content": WRITE_REPORT_SYSTEM},
            {
                "role": "user",
                "content": build_write_report_user_prompt(
                    topic=state["topic"],
                    audience_tag=state.get("audience_tag"),
                    sub_queries=brief["sub_queries"],
                    cited_claims=cited_claims,
                ),
            },
        ]
        narrative = await asyncio.to_thread(llm_client.complete, messages)
        sources_section = _build_sources_section(sources, citation_numbers)
        brief["report_markdown"] = f"{narrative.strip()}\n\n{sources_section}\n"

        return {"brief": brief}

    return node

