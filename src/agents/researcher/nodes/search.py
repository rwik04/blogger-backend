"""Steps 2 and 4 — parallel search and selective scrape. RESEARCHER.md §3.

`make_search_subquery_fn` is the fan-out item function (one call per
sub-question, concurrency-bounded by the graph engine's `add_fanout_node`).
`make_selective_scrape_node` runs once per round after filtering, only for
sources whose inline search content came back truncated/empty.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from urllib.parse import urlparse

from agents.researcher.state import RawSearchHit
from graph.engine import ItemFn, NodeFn
from mcpclient.client import MCPClient, extract_text
from mcp.types import CallToolResult

logger = logging.getLogger(__name__)

_MIN_INLINE_CONTENT_CHARS = 400
_RESULTS_PER_SUBQUERY = 5
_MAX_SCRAPES_PER_ROUND = 4


def _make_source_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _parse_search_results(result: CallToolResult) -> list[RawSearchHit]:
    """Best-effort parsing of Exa's `web_search_exa` response. Prefers
    `structuredContent` (a list of result dicts) when present, falls back to
    parsing the text content as JSON, and skips anything that isn't
    recognizable rather than raising — a single sub-query returning something
    unparseable shouldn't fail the whole round.
    """
    items: list[Any] = []
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        items = structured.get("results") or structured.get("items") or []
    elif isinstance(structured, list):
        items = structured

    if not items:
        text = extract_text(result)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                items = parsed.get("results") or parsed.get("items") or []
            elif isinstance(parsed, list):
                items = parsed
        except json.JSONDecodeError:
            logger.warning("web_search_exa returned non-JSON, non-structured content; skipping")
            items = []

    hits: list[RawSearchHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("link")
        if not url:
            continue
        content = item.get("text") or item.get("content") or item.get("snippet") or ""
        hits.append(
            RawSearchHit(
                source_id=_make_source_id(url),
                url=url,
                title=item.get("title") or url,
                domain=_domain(url),
                content=content,
                needs_scrape=len(content.strip()) < _MIN_INLINE_CONTENT_CHARS,
            )
        )
    return hits


def make_search_subquery_fn(mcp_client: MCPClient) -> ItemFn:
    async def search_one(sub_query: str, _state: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await mcp_client.call_tool(
                "web_search_exa", {"query": sub_query, "numResults": _RESULTS_PER_SUBQUERY}
            )
        except Exception as exc:
            # A single sub-query failing (timeout, 429) shouldn't fail the round —
            # RESEARCHER.md §8. It's dropped; the round proceeds with the rest.
            logger.warning("web_search_exa failed for sub-query %r: %s", sub_query, exc)
            return {"sub_query": sub_query, "hits": []}

        return {"sub_query": sub_query, "hits": _parse_search_results(result)}

    return search_one


def make_selective_scrape_node(mcp_client: MCPClient) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        hits: list[RawSearchHit] = state.get("round_hits", [])
        to_scrape = [h for h in hits if h["needs_scrape"]][:_MAX_SCRAPES_PER_ROUND]

        for hit in to_scrape:
            try:
                result = await mcp_client.call_tool("crawling_exa", {"url": hit["url"]})
                text = extract_text(result)
                if text.strip():
                    hit["content"] = text
                    hit["needs_scrape"] = False
            except Exception as exc:
                logger.warning("crawling_exa failed for %s: %s", hit["url"], exc)

        return {"round_hits": hits}

    return node
