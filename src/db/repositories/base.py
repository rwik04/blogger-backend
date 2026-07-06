"""Shared repository behavior for every per-agent repository: `agent_events`
emission and `blog_runs.status` updates. Both are identical across agents
(Researcher, Strategist, and whatever comes next) — pulled out here once
rather than re-duplicated per agent, so agent-specific repositories only
need to add their own persistence methods (e.g. `save_research_brief`,
`save_strategist_output`).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import Engine, insert, select, update

from db.tables import agent_events, agent_steps, blog_runs

logger = logging.getLogger(__name__)


class RunNotFoundError(Exception):
    """Raised when a `run_id` has no `blog_runs` row."""


class BaseAgentRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Fetches the `blog_runs` row for `run_id` (topic/audience_tag/status) —
        needed by every downstream agent since the topic isn't carried on any
        agent's own output contract (`ResearchBrief`, `StrategistOutput`, ...).
        """
        with self._engine.begin() as conn:
            row = conn.execute(select(blog_runs).where(blog_runs.c.id == run_id)).mappings().first()
        if row is None:
            raise RunNotFoundError(f"No blog_runs row for run_id={run_id!r}")
        return dict(row)

    def load_agent_output(self, run_id: str, agent: str) -> dict[str, Any] | None:
        """Loads the most recently persisted `agent_steps.output` JSON blob for
        `run_id`/`agent` (e.g. `agent="researcher"`), or `None` if that agent
        hasn't successfully completed for this run yet. Callers validate the
        raw dict back into their own agent's pydantic model and raise a more
        specific not-found error with agent-appropriate wording.
        """
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    select(agent_steps.c.output)
                    .where(agent_steps.c.run_id == run_id, agent_steps.c.agent == agent)
                    .order_by(agent_steps.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return row["output"] if row is not None else None

    def set_run_status(self, run_id: str, status: str) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(update(blog_runs).where(blog_runs.c.id == run_id).values(status=status))
        except Exception:
            logger.exception("Failed to update blog_runs.status (run_id=%s status=%s)", run_id, status)

    def emit_event(self, run_id: str | None, step: str, phase: str, detail: dict[str, Any] | None) -> None:
        if run_id is None:
            logger.warning("emit_event called without run_id (step=%s phase=%s)", step, phase)
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(agent_events).values(
                        id=str(uuid.uuid4()),
                        run_id=run_id,
                        step=step,
                        phase=phase,
                        detail=detail,
                    )
                )
        except Exception:
            # Event emission is best-effort observability, not the run's
            # correctness path — a DB hiccup here shouldn't fail the step.
            logger.exception("Failed to emit agent_event (run_id=%s step=%s phase=%s)", run_id, step, phase)
