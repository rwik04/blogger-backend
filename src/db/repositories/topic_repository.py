"""Persistence for the Topic Generator agent.

Deliberately doesn't extend `BaseAgentRepository` — that class's `get_run`/
`emit_event`/`set_run_status` are all keyed on `blog_runs`/`agent_events`,
and topic generation happens *before* any `blog_runs` row exists. This
repository owns its own parallel "batch" concept (`topic_batches`/
`topic_batch_events`) instead, following the same shape (status transitions,
started/done/failed events) for consistency, plus the `topics` table itself
(candidate storage, pg_trgm-based dedup lookups, selection).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import Engine, func, insert, select, text, update

from db.repositories.errors import TopicBatchNotFoundError, TopicNotFoundError
from db.tables import topic_batch_events, topic_batches, topics

logger = logging.getLogger(__name__)

_DEFAULT_EVENTS_LIMIT = 50
_SIMILARITY_NOISE_FLOOR = 0.15
"""Below this, a trigram match is just shared common words — not worth
returning as a dedup candidate at all (TOPIC_GENERATOR.md §4 only cares
about the 0.25+ bands)."""


class TopicRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # --- batch lifecycle -----------------------------------------------

    def create_batch(
        self,
        batch_id: str,
        mode: str,
        user_instruction: str | None,
        count: int,
        auto_approve: bool,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(topic_batches).values(
                    id=batch_id,
                    mode=mode,
                    user_instruction=user_instruction,
                    count=count,
                    auto_approve=auto_approve,
                    status="running",
                )
            )

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        with self._engine.begin() as conn:
            row = conn.execute(select(topic_batches).where(topic_batches.c.id == batch_id)).mappings().first()
        if row is None:
            raise TopicBatchNotFoundError(f"No topic_batches row for batch_id={batch_id!r}")
        return dict(row)

    def set_batch_status(self, batch_id: str, status: str, error: str | None = None) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    update(topic_batches)
                    .where(topic_batches.c.id == batch_id)
                    .values(status=status, error=error)
                )
        except Exception:
            logger.exception("Failed to update topic_batches.status (batch_id=%s status=%s)", batch_id, status)

    def emit_batch_event(
        self, batch_id: str | None, step: str, phase: str, detail: dict[str, Any] | None
    ) -> None:
        if batch_id is None:
            logger.warning("emit_batch_event called without batch_id (step=%s phase=%s)", step, phase)
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(topic_batch_events).values(
                        id=str(uuid.uuid4()),
                        batch_id=batch_id,
                        step=step,
                        phase=phase,
                        detail=detail,
                    )
                )
        except Exception:
            logger.exception(
                "Failed to emit topic_batch_event (batch_id=%s step=%s phase=%s)", batch_id, step, phase
            )

    def list_batch_events(self, batch_id: str, limit: int = _DEFAULT_EVENTS_LIMIT) -> list[dict[str, Any]]:
        with self._engine.begin() as conn:
            rows = (
                conn.execute(
                    select(
                        topic_batch_events.c.step,
                        topic_batch_events.c.phase,
                        topic_batch_events.c.detail,
                        topic_batch_events.c.created_at,
                    )
                    .where(topic_batch_events.c.batch_id == batch_id)
                    .order_by(topic_batch_events.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    # --- dedup lookups ----------------------------------------------------

    def find_similar_topics(self, title: str, limit: int = 5) -> list[dict[str, Any]]:
        """Trigram similarity of `title` against every previously generated
        topic's title (TOPIC_GENERATOR.md §4), best match first. Uses
        Postgres's `pg_trgm` `similarity()` function directly in SQL — no
        embeddings, no new Python dependency.
        """
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(
                    topics.c.id,
                    topics.c.title,
                    func.similarity(topics.c.title, title).label("similarity_score"),
                )
                .where(func.similarity(topics.c.title, title) >= _SIMILARITY_NOISE_FLOOR)
                .order_by(text("similarity_score DESC"))
                .limit(limit)
            ).mappings().all()
        return [dict(row) for row in rows]

    # --- candidate persistence / retrieval ---------------------------------

    def save_candidates(self, batch_id: str, candidates: list[dict[str, Any]]) -> None:
        with self._engine.begin() as conn:
            for candidate in candidates:
                conn.execute(
                    insert(topics).values(
                        id=candidate["candidate_id"],
                        batch_id=batch_id,
                        title=candidate["title"],
                        one_line_summary=candidate["one_line_summary"],
                        subject=candidate["subject"],
                        gs_papers=candidate["gs_papers"],
                        why_this_topic=candidate["why_this_topic"],
                        current_relevance=candidate["current_relevance"],
                        trigger_source_url=candidate["trigger_source_url"],
                        dedup_status=candidate["dedup_status"],
                        similarity_score=candidate["similarity_score"],
                        status=candidate.get("status", "suggested"),
                    )
                )

    def list_topics(
        self,
        status: str | None = None,
        subject: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = select(topics).order_by(topics.c.created_at.desc())
        if status is not None:
            query = query.where(topics.c.status == status)
        if subject is not None:
            query = query.where(topics.c.subject == subject)
        query = query.limit(limit).offset(offset)

        with self._engine.begin() as conn:
            rows = conn.execute(query).mappings().all()
        return [dict(row) for row in rows]

    def get_topic(self, topic_id: str) -> dict[str, Any]:
        with self._engine.begin() as conn:
            row = conn.execute(select(topics).where(topics.c.id == topic_id)).mappings().first()
        if row is None:
            raise TopicNotFoundError(f"No topics row for topic_id={topic_id!r}")
        return dict(row)

    def mark_topic_selected(self, topic_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(topics).where(topics.c.id == topic_id).values(status="selected"))
