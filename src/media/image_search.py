"""Google Images search via SerpAPI — resolves a Finisher media prompt (a
text description meant for an image model) to a real, hotlinkable image URL
so the published blog can render an actual banner/infographic instead of
just showing the prompt text.

Best-effort by design: a missing API key, an empty result set, or a request
failure all just yield `None` rather than raising, so image resolution never
takes down an otherwise-successful Finisher run — same "observability, not
correctness path" precedent as `graph.events` emission.
"""

from __future__ import annotations

import logging
import os

import serpapi

logger = logging.getLogger(__name__)

_ENGINE = "google_images_light"

# Meta's crawler-proxy hosts ("lookaside"/CDN links Google Images sometimes
# surfaces as `original` for Instagram/Facebook-hosted photos) reject
# hotlinking from any page that isn't Meta's own — they 403 when rendered as
# a plain <img src>, which is exactly what a "showing alt text" broken image
# looks like. `thumbnail` is always served from Google's own gstatic proxy
# (the same host that backs the Google Images grid in a browser), so it's
# never blocked — safe to fall back to per-result rather than skipping the
# whole search result.
_BLOCKED_ORIGINAL_HOST_SUBSTRINGS = (
    "lookaside.instagram.com",
    "lookaside.fbsbx.com",
    "cdninstagram.com",
    "fbcdn.net",
    "scontent",
)


def _is_hotlink_blocked(url: str) -> bool:
    return any(host in url for host in _BLOCKED_ORIGINAL_HOST_SUBSTRINGS)


class ImageSearchClient:
    def __init__(self, api_key: str) -> None:
        self._client = serpapi.Client(api_key=api_key)

    def search_image_url(self, query: str) -> str | None:
        """Runs a synchronous Google Images search and returns the first
        usable image URL, or `None` if nothing usable came back. Callers on
        the async graph should offload this via `asyncio.to_thread` — the
        underlying `requests` call is blocking.
        """
        try:
            results = self._client.search({"engine": _ENGINE, "q": query})
        except Exception:
            logger.exception("SerpAPI image search failed for query=%r", query)
            return None

        images = results.get("images_results") or []
        if not images:
            return None

        first = images[0]
        original = first.get("original")
        if original and not _is_hotlink_blocked(original):
            return original
        return first.get("thumbnail")

    @classmethod
    def from_env(cls) -> "ImageSearchClient | None":
        """Returns `None` (rather than raising) when `SERPAPI_API_KEY` isn't
        set — image resolution is an optional enhancement, unlike the
        required `OPENAI_API_KEY`/`EXA_API_KEY` env vars other agents use.
        """
        api_key = os.environ.get("SERPAPI_API_KEY")
        if not api_key:
            return None
        return cls(api_key=api_key)
