"""Resolves each `plan_media` prompt to a real image URL via Google Images
(SerpAPI) before persistence. FINISHER.md's media planning stops at
prompt/alt-text (an image-generation prompt, not an image); this node turns
that into something actually renderable in the published blog, using the
prompt itself as the search query.

Runs after `plan_media`, before `persist_finisher`. Skips entirely (leaving
every `image_url` as `None`) when no `SERPAPI_API_KEY` is configured —
image resolution is a best-effort enhancement, not part of the pipeline's
correctness path.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.finisher.models import MediaPrompt
from graph.engine import NodeFn
from media.image_search import ImageSearchClient


def make_fetch_media_images_node(image_client: ImageSearchClient | None) -> NodeFn:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        media = [MediaPrompt.model_validate(m) for m in state.get("media", [])]

        if image_client is None:
            summary = "Skipped image resolution (no SERPAPI_API_KEY configured)"
            return {"media": [m.model_dump() for m in media], "_event_summary": summary}
        if not media:
            return {"media": [], "_event_summary": "No media prompts to resolve"}

        async def resolve(item: MediaPrompt) -> MediaPrompt:
            url = await asyncio.to_thread(image_client.search_image_url, item.prompt)
            return item.model_copy(update={"image_url": url})

        resolved = await asyncio.gather(*(resolve(item) for item in media))
        found = sum(1 for item in resolved if item.image_url)
        summary = f"Resolved {found}/{len(resolved)} image(s) via Google Images"
        return {"media": [m.model_dump() for m in resolved], "_event_summary": summary}

    return node
