"""Public interface for the Topic Generator agent.

`TopicGenerator` owns the agent's dependencies (LLM client, MCP client
factory, DB repository) and exposes a single `run()` that drives one
end-to-end pass through `agents.topic_generator.pipeline`. Unlike the other
four agents, this one runs *before* a `blog_runs` row exists — it tracks its
own progress via `topic_batches`/`topic_batch_events` (see
`TopicRepository`), not `agent_events`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from agents.topic_generator.models import TopicGeneratorInput, TopicGeneratorMode, TopicGeneratorOutput
from agents.topic_generator.pipeline import build_topic_generator_graph
from db.engine import get_engine
from db.repositories.topic_repository import TopicRepository
from llm.client import LLMClient
from mcpclient.client import get_exa_client

logger = logging.getLogger(__name__)

_DEFAULT_REASONING_EFFORT = "low"


class TopicGenerator:
    def __init__(
        self,
        llm_client: LLMClient,
        repo: TopicRepository,
        reasoning_effort: str | None = _DEFAULT_REASONING_EFFORT,
    ) -> None:
        self._llm_client = llm_client
        self._repo = repo
        self._reasoning_effort = reasoning_effort

    @classmethod
    def from_env(cls) -> "TopicGenerator":
        """Builds a `TopicGenerator` wired to real OpenAI and Postgres from env
        config — the constructor itself takes plain dependencies so tests can
        inject fakes without touching env vars. The Exa MCP client is opened
        per-`run()` call (same lifecycle as the Researcher's), not held here.
        """
        llm_client = LLMClient(
            provider="openai",
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
        repo = TopicRepository(get_engine())
        reasoning_effort = os.environ.get("TOPIC_GENERATOR_REASONING_EFFORT", _DEFAULT_REASONING_EFFORT) or None
        return cls(llm_client=llm_client, repo=repo, reasoning_effort=reasoning_effort)

    async def run(self, input: TopicGeneratorInput, batch_id: str | None = None) -> TopicGeneratorOutput:
        batch_id = batch_id or str(uuid.uuid4())

        await asyncio.to_thread(
            self._repo.create_batch,
            batch_id,
            input.mode.value,
            input.user_instruction,
            input.count,
            input.auto_approve,
        )

        initial_state: dict[str, Any] = {
            "run_id": batch_id,  # graph.events.with_events reads state["run_id"]
            "batch_id": batch_id,
            "mode": input.mode.value if isinstance(input.mode, TopicGeneratorMode) else input.mode,
            "user_instruction": input.user_instruction,
            "count": input.count,
            "auto_approve": input.auto_approve,
        }

        try:
            async with get_exa_client() as mcp_client:
                compiled_graph = build_topic_generator_graph(
                    llm_client=self._llm_client,
                    mcp_client=mcp_client,
                    repo=self._repo,
                    reasoning_effort=self._reasoning_effort,
                    emitter=self._emit_event_async,
                )
                final_state = await compiled_graph.arun(initial_state)
        except Exception:
            logger.exception("Topic Generator run failed (batch_id=%s)", batch_id)
            await asyncio.to_thread(self._repo.set_batch_status, batch_id, "failed", "unhandled exception")
            raise

        await asyncio.to_thread(self._repo.set_batch_status, batch_id, "done")
        return TopicGeneratorOutput.model_validate(final_state["output"])

    async def _emit_event_async(
        self, batch_id: str | None, step: str, phase: str, detail: dict[str, Any] | None
    ) -> None:
        await asyncio.to_thread(self._repo.emit_batch_event, batch_id, step, phase, detail)
