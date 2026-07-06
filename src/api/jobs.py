"""Background-task safety net for fire-and-forget agent runs.

Every agent already sets `blog_runs.status = "failed"` and logs on its own
exceptions (see each agent's `run()`), so this wrapper isn't the primary
error-handling path — it just guarantees an unhandled exception inside a
`BackgroundTasks`-scheduled coroutine gets logged instead of silently
vanishing (FastAPI/Starlette otherwise only logs these to stderr with no
context about which run/stage it was).
"""

from __future__ import annotations

import logging
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


async def run_and_log(coro: Coroutine[Any, Any, Any], description: str) -> None:
    try:
        await coro
    except Exception:
        logger.exception("Background job failed: %s", description)
