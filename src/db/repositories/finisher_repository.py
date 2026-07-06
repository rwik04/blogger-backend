"""Persistence for the Finisher agent: loading the upstream `ResearchBrief`,
`StrategistOutput`, and `WriterOutput`, plus saving the resulting
`FinisherOutput` — `seo_audits`/`quiz_questions`/`media_assets` tables plus
a staged `published_blogs` row and the full JSON blob on
`agent_steps.output`, mirroring the Researcher/Strategist/Writer
persistence pattern (FINISHER.md §6).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import insert

from agents.researcher.models import ResearchBrief
from agents.strategist.models import StrategistOutput
from agents.writer.models import WriterOutput
from db.repositories.base import BaseAgentRepository
from db.tables import agent_steps, media_assets, published_blogs, quiz_questions, seo_audits

logger = logging.getLogger(__name__)


class ResearchBriefNotFoundError(Exception):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Researcher."""


class StrategistOutputNotFoundError(Exception):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Strategist."""


class WriterOutputNotFoundError(Exception):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Writer —
    i.e. `write`/`agents.writer` hasn't successfully completed for this run yet.
    """


class FinisherRepository(BaseAgentRepository):
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

    def load_writer_output(self, run_id: str) -> WriterOutput:
        output = self.load_agent_output(run_id, "writer")
        if output is None:
            raise WriterOutputNotFoundError(
                f"No persisted Writer output for run_id={run_id!r} — run the Writer agent first"
            )
        return WriterOutput.model_validate(output)

    def save_finisher_output(self, output: dict[str, Any]) -> None:
        run_id = output["run_id"]
        seo_audit = output["seo_audit"]

        with self._engine.begin() as conn:
            conn.execute(
                insert(seo_audits).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    keyword_density=seo_audit["keyword_density"],
                    heading_issues=seo_audit["heading_issues"],
                    meta_description_ok=seo_audit["meta_description_ok"],
                    internal_link_suggestions=seo_audit["internal_link_suggestions"],
                )
            )

            for question in output["questions"]:
                conn.execute(
                    insert(quiz_questions).values(
                        id=question["question_id"],
                        run_id=run_id,
                        stem=question["stem"],
                        statements=question["statements"],
                        options=question["options"],
                        correct_option=question["correct_option"],
                        explanation=question["explanation"],
                        related_section_id=question["related_section_id"],
                    )
                )

            for media in output["media"]:
                conn.execute(
                    insert(media_assets).values(
                        id=media["media_id"],
                        run_id=run_id,
                        kind=media["kind"],
                        section_id=media["section_id"],
                        prompt=media["prompt"],
                        alt_text=media["alt_text"],
                        status="pending",
                    )
                )

            conn.execute(
                insert(published_blogs).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    final_title=output["final_title"],
                    tags=output["final_tags"],
                    subject=output["subject"],
                    published_at=None,
                    canonical_url=None,
                )
            )

            conn.execute(
                insert(agent_steps).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    agent="finisher",
                    status="done",
                    output=output,
                )
            )
