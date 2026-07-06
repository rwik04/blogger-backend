"""Small text helpers for building human-readable `_event_summary` strings
out of lists of search/research queries — shared by the Researcher and Topic
Generator pipelines, both of which fan out over LLM-planned query lists and
want to show "what am I looking up right now" on the dashboard without
dumping full (often long) question text into the event log.
"""

from __future__ import annotations

_MAX_QUERY_CHARS = 70
_MAX_QUERIES_SHOWN = 2


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def preview_queries(queries: list[str], limit: int = _MAX_QUERIES_SHOWN) -> str:
    shown = [_truncate(q, _MAX_QUERY_CHARS) for q in queries[:limit]]
    preview = "; ".join(shown)
    if len(queries) > limit:
        preview += f" (+{len(queries) - limit} more)"
    return preview
