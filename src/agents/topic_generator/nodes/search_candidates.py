"""Step 2 — lightweight search. TOPIC_GENERATOR.md §3 step 2: shallow, top-5
results per query, no crawling/full-page extraction — this is a scan for
candidate stories, not the Researcher's deep multi-source research.

Self-contained parsing (not shared with `agents.researcher.nodes.search`)
since this only needs title/url/snippet, not the Researcher's
`RawSearchHit`/`needs_scrape` machinery.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from graph.engine import ItemFn
from mcp.types import CallToolResult
from mcpclient.client import MCPClient, extract_text

logger = logging.getLogger(__name__)

_RESULTS_PER_QUERY = 5
_FIELD_RE = re.compile(r"^(Title|URL|Published|Author|Highlights|Text):\s*(.*)$")


def _parse_text_entries(text: str) -> list[dict[str, str]]:
    """Fallback parser for exa-mcp-server's plain-text `web_search_exa`
    output — one entry per result, `Field: value` blocks separated by `---`.
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    field: str | None = None

    def flush() -> None:
        if current.get("URL"):
            entries.append(dict(current))
        current.clear()

    for line in text.splitlines():
        if line.strip() == "---":
            flush()
            field = None
            continue
        match = _FIELD_RE.match(line)
        if match:
            field = match.group(1)
            current[field] = match.group(2).strip()
        elif field is not None:
            current[field] = (current.get(field, "") + "\n" + line).strip()
    flush()
    return entries


def _parse_light_hits(result: CallToolResult) -> list[dict[str, str]]:
    """Best-effort parsing of `web_search_exa`'s response into plain
    `{title, url, snippet}` dicts — prefers `structuredContent`, falls back
    to JSON text, then to the plain-text format, skipping anything
    unrecognizable rather than raising.
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
            items = _parse_text_entries(text)
            if not items:
                logger.warning("web_search_exa returned unrecognized content; skipping")

    hits: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("link") or item.get("URL")
        if not url:
            continue
        snippet = (
            item.get("text") or item.get("content") or item.get("snippet") or item.get("Highlights") or item.get("Text") or ""
        )
        title = item.get("title") or item.get("Title") or url
        hits.append({"title": title, "url": url, "snippet": snippet.strip()[:600]})
    return hits


def make_search_query_fn(mcp_client: MCPClient) -> ItemFn:
    async def search_one(query: str, _state: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await mcp_client.call_tool("web_search_exa", {"query": query, "numResults": _RESULTS_PER_QUERY})
        except Exception as exc:
            # A single query failing (timeout, 429) shouldn't fail the whole
            # scan (TOPIC_GENERATOR.md §8 — a quiet subject just gets skipped).
            logger.warning("web_search_exa failed for query %r: %s", query, exc)
            return {"query": query, "hits": []}

        return {"query": query, "hits": _parse_light_hits(result)}

    return search_one
