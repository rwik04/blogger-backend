"""The single entry point for running a blog end to end.

Historically each stage (Researcher -> Strategist -> Writer -> Finisher) was
started by its own `POST /runs/.../{stage}` call, and nothing chained them
together — a human had to click "Run" after every stage finished. This module
is the supervisor `CLAUDE.md` describes as missing: "a new caller invoking
`Agent.run()` in sequence" that sits above the four agents.

`PipelineSupervisor.start()` runs Researcher and then automatically walks
Strategist -> Writer -> Finisher, checking `blog_runs.paused` after every
stage completes and before starting the next one. There is no mid-stage
cancellation (an in-flight LLM/graph call always runs to completion) — pause
only stops the chain from advancing at the next stage *boundary*. Toggling
`paused` back off doesn't restart anything by itself; `PipelineSupervisor.resume()`
is the explicit "continue from where it left off" call the `/resume` route
makes.
"""

from __future__ import annotations

import logging

from agents.finisher.finisher import Finisher
from agents.finisher.models import FinisherInput
from agents.researcher.models import ResearcherInput
from agents.researcher.researcher import Researcher
from agents.strategist.models import StrategistInput
from agents.strategist.strategist import Strategist
from agents.writer.models import WriterInput
from agents.writer.writer import Writer
from api.concurrency import run_sync
from db.engine import get_engine
from db.repositories.base import BaseAgentRepository
from db.repositories.finisher_repository import FinisherRepository
from db.repositories.strategist_repository import StrategistRepository
from db.repositories.writer_repository import WriterRepository

logger = logging.getLogger(__name__)

# What stage comes after which. `None`/missing means "nothing left to run".
_STAGE_AFTER = {"research": "strategize", "strategize": "write", "write": "finish"}


class PipelineSupervisor:
    def __init__(self, researcher: Researcher, strategist: Strategist, writer: Writer, finisher: Finisher) -> None:
        self._researcher = researcher
        self._strategist = strategist
        self._writer = writer
        self._finisher = finisher

    async def start(
        self,
        run_id: str,
        topic: str,
        audience_tag: str | None = None,
        topic_id: str | None = None,
    ) -> None:
        """Entry point for a brand-new run: runs the Researcher, then keeps
        going through Strategist/Writer/Finisher on its own unless/until the
        run is paused.
        """
        researcher_input = ResearcherInput(run_id=run_id, topic=topic, audience_tag=audience_tag, topic_id=topic_id)
        await self._researcher.run(researcher_input)
        await self._advance(run_id, after="research")

    async def resume(self, run_id: str) -> None:
        """Re-entry point for `POST /runs/{run_id}/resume`. Only acts if the
        run is genuinely idle at a stage boundary (`status == "done"`) — if a
        stage is still mid-flight, that stage's own `_advance` call will
        already pick up the cleared `paused` flag once it finishes, so
        triggering another one here would double-run the next stage.
        """
        base_repo = BaseAgentRepository(get_engine())
        run = await run_sync(base_repo.get_run, run_id)
        if run.get("status") != "done":
            logger.info("Resume no-op for run %s: status=%s (not idle at a boundary)", run_id, run.get("status"))
            return

        last_stage = await run_sync(self._last_completed_stage, run_id)
        if last_stage is None or last_stage == "finish":
            return  # nothing persisted yet, or the pipeline already finished

        await self._advance(run_id, after=last_stage)

    def _last_completed_stage(self, run_id: str) -> str | None:
        base_repo = BaseAgentRepository(get_engine())
        if base_repo.load_agent_output(run_id, "finisher") is not None:
            return "finish"
        if base_repo.load_agent_output(run_id, "writer") is not None:
            return "write"
        if base_repo.load_agent_output(run_id, "strategist") is not None:
            return "strategize"
        if base_repo.load_agent_output(run_id, "researcher") is not None:
            return "research"
        return None

    async def _advance(self, run_id: str, after: str) -> None:
        next_stage = _STAGE_AFTER.get(after)
        if next_stage is None:
            return  # Finisher was the last stage — pipeline complete

        base_repo = BaseAgentRepository(get_engine())
        run = await run_sync(base_repo.get_run, run_id)
        if run.get("paused"):
            logger.info("Run %s is paused — holding before %s", run_id, next_stage)
            return

        if next_stage == "strategize":
            await self._run_strategize(run_id)
        elif next_stage == "write":
            await self._run_write(run_id)
        elif next_stage == "finish":
            await self._run_finish(run_id)

        await self._advance(run_id, after=next_stage)

    async def _run_strategize(self, run_id: str) -> None:
        repo = StrategistRepository(get_engine())
        run = await run_sync(repo.get_run, run_id)
        research_brief = await run_sync(repo.load_research_brief, run_id)
        strategist_input = StrategistInput(
            run_id=run_id,
            topic=run["topic"],
            audience_tag=run.get("audience_tag"),
            research_brief=research_brief,
        )
        await self._strategist.run(strategist_input)

    async def _run_write(self, run_id: str) -> None:
        repo = WriterRepository(get_engine())
        run = await run_sync(repo.get_run, run_id)
        research_brief = await run_sync(repo.load_research_brief, run_id)
        strategist_output = await run_sync(repo.load_strategist_output, run_id)
        writer_input = WriterInput(
            run_id=run_id,
            topic=run["topic"],
            audience_tag=run.get("audience_tag"),
            research_brief=research_brief,
            strategist_output=strategist_output,
        )
        await self._writer.run(writer_input)

    async def _run_finish(self, run_id: str) -> None:
        repo = FinisherRepository(get_engine())
        run = await run_sync(repo.get_run, run_id)
        research_brief = await run_sync(repo.load_research_brief, run_id)
        strategist_output = await run_sync(repo.load_strategist_output, run_id)
        writer_output = await run_sync(repo.load_writer_output, run_id)
        finisher_input = FinisherInput(
            run_id=run_id,
            topic=run["topic"],
            audience_tag=run.get("audience_tag"),
            include_quiz=True,
            research_brief=research_brief,
            strategist_output=strategist_output,
            writer_output=writer_output,
        )
        await self._finisher.run(finisher_input)
