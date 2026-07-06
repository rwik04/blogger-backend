"""Persistence for the Strategist agent: loading the upstream `ResearchBrief`
(and its parent run's `topic`/`audience_tag`) plus saving the resulting
`StrategistOutput` — normalized `seo_plans`/`outline_sections` tables and the
full JSON blob on `agent_steps.output`, mirroring the Researcher's
persistence pattern (RESEARCHER.md §5 / STRATEGIST.md §4).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import insert

from agents.researcher.models import ResearchBrief
from db.repositories.base import BaseAgentRepository, RunNotFoundError
from db.tables import agent_steps, outline_sections, seo_plans

logger = logging.getLogger(__name__)

__all__ = ["StrategistRepository", "RunNotFoundError", "ResearchBriefNotFoundError"]


class ResearchBriefNotFoundError(Exception):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Researcher —
    i.e. `research`/`agents.researcher` hasn't successfully completed for this run yet.
    """


class StrategistRepository(BaseAgentRepository):
    def load_research_brief(self, run_id: str) -> ResearchBrief:
        """Loads the most recently persisted Researcher `agent_steps.output`
        for `run_id` and validates it back into a `ResearchBrief`.
        """
        output = self.load_agent_output(run_id, "researcher")
        if output is None:
            raise ResearchBriefNotFoundError(
                f"No persisted Researcher output for run_id={run_id!r} — run the Researcher agent first"
            )
        return ResearchBrief.model_validate(output)

    def save_strategist_output(self, output: dict[str, Any]) -> None:
        run_id = output["run_id"]
        seo_plan = output["seo_plan"]

        with self._engine.begin() as conn:
            conn.execute(
                insert(seo_plans).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    primary_keyword=seo_plan["primary_keyword"],
                    secondary_keywords=seo_plan["secondary_keywords"],
                    meta_title=seo_plan["meta_title"],
                    meta_description=seo_plan["meta_description"],
                    slug=seo_plan["slug"],
                )
            )

            for section in output["outline"]:
                conn.execute(
                    insert(outline_sections).values(
                        id=str(uuid.uuid4()),
                        run_id=run_id,
                        section_id=section["section_id"],
                        heading=section["heading"],
                        target_keyword=section["target_keyword"],
                        grounded=section["grounded"],
                        order_index=section["order_index"],
                    )
                )

            conn.execute(
                insert(agent_steps).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    agent="strategist",
                    status="done",
                    output=output,
                )
            )
