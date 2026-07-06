"""Public interface for the Finisher agent.

`Finisher` owns the agent's dependencies (LLM client, the DB repository) and
exposes a single `run()` that drives one end-to-end pass through the
`audit_seo -> [quiz steps] -> plan_media -> persist_finisher` pipeline built
in `agents.finisher.pipeline`.

Like the Strategist and Writer, this agent doesn't run standalone from a
fresh topic — it always starts from an already-persisted `ResearchBrief`,
`StrategistOutput`, and `WriterOutput` for a given `run_id` (see
`FinisherRepository`, wired up by `__main__.py`). No orchestrator chains
Writer -> Finisher yet; that's explicit future work, same as every other
stage boundary in this pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from agents.finisher.models import FinisherInput, FinisherOutput
from agents.finisher.pipeline import build_finisher_graph
from db.engine import get_engine
from db.repositories.finisher_repository import FinisherRepository
from llm.client import LLMClient
from media.image_search import ImageSearchClient

logger = logging.getLogger(__name__)

_DEFAULT_REASONING_EFFORT = "medium"


class Finisher:
    def __init__(
        self,
        llm_client: LLMClient,
        repo: FinisherRepository,
        reasoning_effort: str | None = _DEFAULT_REASONING_EFFORT,
        image_client: ImageSearchClient | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._repo = repo
        self._reasoning_effort = reasoning_effort
        self._image_client = image_client

    @classmethod
    def from_env(cls) -> "Finisher":
        """Builds a `Finisher` wired to real OpenAI and Postgres from env
        config — the constructor itself takes plain dependencies so tests
        can inject fakes without touching env vars.
        """
        llm_client = LLMClient(
            provider="openai",
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
        repo = FinisherRepository(get_engine())
        reasoning_effort = os.environ.get("FINISHER_REASONING_EFFORT", _DEFAULT_REASONING_EFFORT) or None
        image_client = ImageSearchClient.from_env()
        return cls(llm_client=llm_client, repo=repo, reasoning_effort=reasoning_effort, image_client=image_client)

    async def run(self, input: FinisherInput) -> FinisherOutput:
        initial_state: dict[str, Any] = {
            "run_id": input.run_id,
            "topic": input.topic,
            "audience_tag": input.audience_tag,
            "include_quiz": input.include_quiz,
            "research_brief": input.research_brief.model_dump(),
            "strategist_output": input.strategist_output.model_dump(),
            "writer_output": input.writer_output.model_dump(),
            "quality_flags": [],
        }

        await asyncio.to_thread(self._repo.set_run_status, input.run_id, "finishing")

        try:
            compiled_graph = build_finisher_graph(
                llm_client=self._llm_client,
                repo=self._repo,
                reasoning_effort=self._reasoning_effort,
                emitter=self._emit_event_async,
                image_client=self._image_client,
            )
            final_state = await compiled_graph.arun(initial_state)
        except Exception:
            await asyncio.to_thread(self._repo.set_run_status, input.run_id, "failed")
            raise

        await asyncio.to_thread(self._repo.set_run_status, input.run_id, "done")
        return FinisherOutput.model_validate(final_state["output"])

    async def _emit_event_async(
        self, run_id: str | None, step: str, phase: str, detail: dict[str, Any] | None
    ) -> None:
        # FinisherRepository.emit_event does blocking DB I/O — offload so it
        # doesn't stall the event loop mid-graph-run.
        await asyncio.to_thread(self._repo.emit_event, run_id, step, phase, detail)
