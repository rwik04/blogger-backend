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
from db.tables import agent_steps, blog_drafts, blog_section_claims, blog_sections

logger = logging.getLogger(__name__)


class ResearchBriefNotFoundError(Exception):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Researcher."""


class StrategistOutputNotFoundError(Exception):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Strategist —
    i.e. `strategize`/`agents.strategist` hasn't successfully completed for this run yet.
    """


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
