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

from sqlalchemy import insert

from db.repositories.base import BaseAgentRepository
from db.tables import agent_steps, blog_runs, research_claim_sources, research_claims, research_sources

logger = logging.getLogger(__name__)


class ResearchRepository(BaseAgentRepository):
    def create_run(
        self, run_id: str, topic: str, audience_tag: str | None, topic_id: str | None = None
    ) -> None:
        """Insert the parent `blog_runs` row for a run before any `agent_events`
        are emitted — `agent_events.run_id` has a FK to `blog_runs.id`, so this
        must happen first or every event emission silently fails.

        `topic_id`, when set, traces this run back to the Topic Generator
        candidate (`topics.id`) it was started from.
        """
        with self._engine.begin() as conn:
            conn.execute(
                insert(blog_runs).values(
                    id=run_id,
                    topic=topic,
                    audience_tag=audience_tag,
                    status="running",
                    topic_id=topic_id,
                )
            )

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
