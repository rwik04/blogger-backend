"""Public interface for the Researcher agent.

`Researcher` owns the agent's dependencies (LLM client, an MCP client
factory, the DB repository) and exposes a single `run()` that drives one
end-to-end run through the iterative search -> compact -> reflect graph
built in `agents.researcher.pipeline`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

from agents.researcher.pipeline import build_researcher_graph
from agents.researcher.models import ResearchBrief, ResearcherInput
from db.engine import get_engine
from db.repositories.research_repository import ResearchRepository
from llm.client import LLMClient
from mcpclient.client import MCPClient, get_exa_client

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = 3

MCPClientFactory = Callable[[], MCPClient]


class Researcher:
    def __init__(
        self,
        llm_client: LLMClient,
        mcp_client_factory: MCPClientFactory,
        repo: ResearchRepository,
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self._llm_client = llm_client
        self._mcp_client_factory = mcp_client_factory
        self._repo = repo
        self._max_iterations = max_iterations

    @classmethod
    def from_env(cls) -> "Researcher":
        """Builds a `Researcher` wired to real OpenAI, Exa, and Postgres from
        env config — the constructor itself takes plain dependencies so tests
        can inject fakes without touching env vars.
        """
        llm_client = LLMClient(
            provider="openai",
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
        repo = ResearchRepository(get_engine())
        max_iterations = int(os.environ.get("RESEARCHER_MAX_ITERATIONS", _DEFAULT_MAX_ITERATIONS))
        return cls(
            llm_client=llm_client,
            mcp_client_factory=get_exa_client,
            repo=repo,
            max_iterations=max_iterations,
        )

    async def run(self, input: ResearcherInput) -> ResearchBrief:
        initial_state: dict[str, Any] = {
            "run_id": input.run_id,
            "topic": input.topic,
            "audience_tag": input.audience_tag,
            "max_iterations": self._max_iterations,
        }

        # Must exist before any agent_events are emitted — agent_events.run_id
        # has a FK to blog_runs.id.
        await asyncio.to_thread(self._repo.create_run, input.run_id, input.topic, input.audience_tag)

        try:
            async with self._mcp_client_factory() as mcp_client:
                compiled_graph = build_researcher_graph(
                    llm_client=self._llm_client,
                    mcp_client=mcp_client,
                    repo=self._repo,
                    emitter=self._emit_event_async,
                )
                final_state = await compiled_graph.arun(initial_state)
        except Exception:
            await asyncio.to_thread(self._repo.set_run_status, input.run_id, "failed")
            raise

        if final_state.get("status") == "needs_review":
            await asyncio.to_thread(self._repo.set_run_status, input.run_id, "needs_review")
            raise RuntimeError(f"Researcher run {input.run_id} failed: {final_state.get('error')}")

        await asyncio.to_thread(self._repo.set_run_status, input.run_id, "done")
        return ResearchBrief.model_validate(final_state["brief"])

    async def _emit_event_async(
        self, run_id: str | None, step: str, phase: str, detail: dict[str, Any] | None
    ) -> None:
        # ResearchRepository.emit_event does blocking DB I/O — offload so it
        # doesn't stall the event loop mid-graph-run.
        await asyncio.to_thread(self._repo.emit_event, run_id, step, phase, detail)
