"""Persistence for the Researcher agent: per-step `agent_events` (dashboard
progress) and the final `ResearchBrief` (normalized tables + the full JSON
blob on `agent_steps.output`, per RESEARCHER.md §5 — normalized tables are
for querying/joining later, the jsonb blob is the source of truth for
replay/debugging).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import Engine, insert

from db.tables import agent_events, agent_steps, research_claim_sources, research_claims, research_sources

logger = logging.getLogger(__name__)


class ResearchRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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

    def save_research_brief(self, brief: dict[str, Any]) -> None:
        run_id = brief["run_id"]

        with self._engine.begin() as conn:
            source_id_map: dict[str, str] = {}
            for source in brief["sources"]:
                row_id = str(uuid.uuid4())
                source_id_map[source["id"]] = row_id
                conn.execute(
                    insert(research_sources).values(
                        id=row_id,
                        run_id=run_id,
                        url=source["url"],
                        title=source["title"],
                        domain=source["domain"],
                        retrieved_at=source["retrieved_at"],
                    )
                )

            for claim in brief["claims"]:
                claim_row_id = str(uuid.uuid4())
                conn.execute(
                    insert(research_claims).values(
                        id=claim_row_id,
                        run_id=run_id,
                        claim_text=claim["text"],
                        confidence=claim["confidence"],
                        contradicted=claim["contradicted"],
                    )
                )
                for source_id in claim["source_ids"]:
                    mapped_source_row_id = source_id_map.get(source_id)
                    if mapped_source_row_id is None:
                        logger.warning(
                            "Claim %s references unknown source_id=%s; skipping join row",
                            claim_row_id,
                            source_id,
                        )
                        continue
                    conn.execute(
                        insert(research_claim_sources).values(
                            claim_id=claim_row_id,
                            source_id=mapped_source_row_id,
                        )
                    )

            conn.execute(
                insert(agent_steps).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    agent="researcher",
                    status="done",
                    output=brief,
                )
            )
