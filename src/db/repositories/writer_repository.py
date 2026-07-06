"""Persistence for the Writer agent: loading the upstream `ResearchBrief` and
`StrategistOutput`, plus saving the resulting `WriterOutput` — normalized
`blog_drafts`/`blog_sections`/`blog_section_claims` tables and the full JSON
blob on `agent_steps.output`, mirroring the Researcher/Strategist persistence
pattern (WRITER.md §4/§6).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, insert, select

from agents.researcher.models import ResearchBrief
from agents.strategist.models import StrategistOutput
from db.repositories.base import BaseAgentRepository
from db.repositories.errors import ResearchBriefNotFoundError, StrategistOutputNotFoundError
from db.tables import agent_steps, blog_drafts, blog_section_claims, blog_sections

__all__ = [
    "WriterRepository",
    "ResearchBriefNotFoundError",
    "StrategistOutputNotFoundError",
]

logger = logging.getLogger(__name__)


class WriterRepository(BaseAgentRepository):
    def load_research_brief(self, run_id: str) -> ResearchBrief:
        output = self.load_agent_output(run_id, "researcher")
        if output is None:
            raise ResearchBriefNotFoundError(
                f"No persisted Researcher output for run_id={run_id!r} — run the Researcher agent first"
            )
        return ResearchBrief.model_validate(output)

    def load_strategist_output(self, run_id: str) -> StrategistOutput:
        output = self.load_agent_output(run_id, "strategist")
        if output is None:
            raise StrategistOutputNotFoundError(
                f"No persisted Strategist output for run_id={run_id!r} — run the Strategist agent first"
            )
        return StrategistOutput.model_validate(output)

    def load_latest_draft(self, run_id: str) -> dict[str, Any] | None:
        """The most recent `blog_drafts` row for `run_id` plus its ordered
        `blog_sections` (each with its `blog_section_claims`), or `None` if
        the Writer hasn't produced a draft yet. Used by `edit_section` to
        find the current text of every section (the one being rewritten,
        plus every other one needed for `draft_so_far` context).
        """
        with self._engine.begin() as conn:
            draft_row = (
                conn.execute(
                    select(blog_drafts.c.id, blog_drafts.c.version, blog_drafts.c.created_by_agent)
                    .where(blog_drafts.c.run_id == run_id)
                    .order_by(blog_drafts.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if draft_row is None:
                return None

            section_rows = (
                conn.execute(
                    select(blog_sections)
                    .where(blog_sections.c.draft_id == draft_row["id"])
                    .order_by(blog_sections.c.order_index.asc())
                )
                .mappings()
                .all()
            )

            sections: list[dict[str, Any]] = []
            for section_row in section_rows:
                claim_rows = conn.execute(
                    select(blog_section_claims.c.claim_id).where(
                        blog_section_claims.c.section_id == section_row["id"]
                    )
                ).all()
                section = dict(section_row)
                section["claim_ids"] = [row[0] for row in claim_rows]
                sections.append(section)

        return {
            "draft_id": draft_row["id"],
            "version": draft_row["version"],
            "created_by_agent": draft_row["created_by_agent"],
            "sections": sections,
        }

    def list_drafts(self, run_id: str) -> list[dict[str, Any]]:
        """Draft version history for `run_id`, newest first — backs
        `GET /runs/{run_id}/write/drafts`.
        """
        with self._engine.begin() as conn:
            rows = (
                conn.execute(
                    select(blog_drafts.c.version, blog_drafts.c.created_by_agent, blog_drafts.c.created_at)
                    .where(blog_drafts.c.run_id == run_id)
                    .order_by(blog_drafts.c.version.desc())
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def get_next_draft_version(self, run_id: str) -> int:
        """1 for a run's first draft, otherwise one more than the highest
        existing `blog_drafts.version` for this run — supports the future
        revision loop (WRITER.md §6) without requiring it today.
        """
        with self._engine.begin() as conn:
            max_version = conn.execute(
                select(func.max(blog_drafts.c.version)).where(blog_drafts.c.run_id == run_id)
            ).scalar()
        return (max_version or 0) + 1

    def save_writer_output(self, output: dict[str, Any]) -> None:
        run_id = output["run_id"]
        draft_id = str(uuid.uuid4())

        with self._engine.begin() as conn:
            conn.execute(
                insert(blog_drafts).values(
                    id=draft_id,
                    run_id=run_id,
                    version=output["draft_version"],
                    created_by_agent="writer",
                )
            )

            for order_index, section in enumerate(output["sections"]):
                section_row_id = str(uuid.uuid4())
                conn.execute(
                    insert(blog_sections).values(
                        id=section_row_id,
                        draft_id=draft_id,
                        section_id=section["section_id"],
                        heading=section["heading"],
                        body_markdown=section["body_markdown"],
                        order_index=order_index,
                        word_count=section["word_count"],
                        tone_notes=section["tone_notes"],
                        retries_used=section["retries_used"],
                        unsupported_gaps=section["unsupported_gaps"],
                    )
                )
                for claim_id in section["claim_ids"]:
                    conn.execute(
                        insert(blog_section_claims).values(
                            section_id=section_row_id,
                            claim_id=claim_id,
                        )
                    )

            conn.execute(
                insert(agent_steps).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    agent="writer",
                    status="done",
                    output=output,
                )
            )
