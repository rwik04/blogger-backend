"""Uniform `agent_events`-style emission around graph node execution.

Applied once by the graph builder (see `agents/researcher/graph.py`) rather
than duplicated inside every node function: each wrapped node emits a
`started` event before running and a `done`/`failed` event after, so the
dashboard gets step-by-step progress without every node author having to
remember to call an emitter.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Protocol

from graph.engine import NodeFn

logger = logging.getLogger(__name__)


class EventEmitter(Protocol):
    def __call__(
        self, run_id: str | None, step: str, phase: str, detail: dict[str, Any] | None
    ) -> Awaitable[None] | None: ...


def log_emitter(run_id: str | None, step: str, phase: str, detail: dict[str, Any] | None) -> None:
    """Default emitter: just logs. Swap for a `ResearchRepository.emit_event`-backed
    emitter in production to persist rows to `agent_events`.
    """
    logger.info("[run=%s] %s -> %s %s", run_id, step, phase, detail or {})


def with_events(
    name: str,
    fn: NodeFn,
    emitter: EventEmitter = log_emitter,
) -> NodeFn:
    async def wrapped(state: dict[str, Any]) -> dict[str, Any] | None:
        run_id = state.get("run_id")
        await _maybe_await(emitter(run_id, name, "started", None))
        started_at = time.monotonic()
        try:
            result = await fn(state)
        except Exception as exc:
            await _maybe_await(
                emitter(run_id, name, "failed", {"error": str(exc)})
            )
            raise
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        await _maybe_await(
            emitter(run_id, name, "done", {"elapsed_ms": elapsed_ms})
        )
        return result

    return wrapped


async def _maybe_await(value: Any) -> None:
    if value is not None and hasattr(value, "__await__"):
        await value
