"""Public interface for the Strategist agent.

`Strategist` owns the agent's dependencies (LLM client, the DB repository)
and exposes a single `run()` that drives one end-to-end pass through the
linear draft-plan -> grounding-check -> persist pipeline built in
`agents.strategist.pipeline`.

Unlike the Researcher, this agent doesn't run standalone from a fresh topic —
it always starts from an already-persisted `ResearchBrief` for a given
`run_id` (see `StrategistRepository.load_research_brief`, wired up by
`__main__.py`). No orchestrator chains Researcher -> Strategist yet; that's
explicit future work.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from agents.strategist.models import StrategistInput, StrategistOutput
from agents.strategist.pipeline import build_strategist_graph
from db.engine import get_engine
from db.repositories.strategist_repository import StrategistRepository
from llm.client import LLMClient

logger = logging.getLogger(__name__)

_DEFAULT_REASONING_EFFORT = "low"


class Strategist:
    def __init__(
        self,
        llm_client: LLMClient,
        repo: StrategistRepository,
        reasoning_effort: str | None = _DEFAULT_REASONING_EFFORT,
    ) -> None:
        self._llm_client = llm_client
        self._repo = repo
        self._reasoning_effort = reasoning_effort

    @classmethod
    def from_env(cls) -> "Strategist":
        """Builds a `Strategist` wired to real OpenAI and Postgres from env
        config — the constructor itself takes plain dependencies so tests
        can inject fakes without touching env vars.
        """
        llm_client = LLMClient(
            provider="openai",
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
        repo = StrategistRepository(get_engine())
        reasoning_effort = os.environ.get("STRATEGIST_REASONING_EFFORT", _DEFAULT_REASONING_EFFORT) or None
        return cls(llm_client=llm_client, repo=repo, reasoning_effort=reasoning_effort)

    async def run(self, input: StrategistInput) -> StrategistOutput:
        initial_state: dict[str, Any] = {
            "run_id": input.run_id,
            "topic": input.topic,
            "audience_tag": input.audience_tag,
            "research_brief": input.research_brief.model_dump(),
        }

        await asyncio.to_thread(self._repo.set_run_status, input.run_id, "strategizing")

        try:
            compiled_graph = build_strategist_graph(
                llm_client=self._llm_client,
                repo=self._repo,
                reasoning_effort=self._reasoning_effort,
                emitter=self._emit_event_async,
            )
            final_state = await compiled_graph.arun(initial_state)
        except Exception:
            await asyncio.to_thread(self._repo.set_run_status, input.run_id, "failed")
            raise

        await asyncio.to_thread(self._repo.set_run_status, input.run_id, "done")
        return StrategistOutput.model_validate(final_state["output"])

    async def _emit_event_async(
        self, run_id: str | None, step: str, phase: str, detail: dict[str, Any] | None
    ) -> None:
        # StrategistRepository.emit_event does blocking DB I/O — offload so it
        # doesn't stall the event loop mid-graph-run.
        await asyncio.to_thread(self._repo.emit_event, run_id, step, phase, detail)
