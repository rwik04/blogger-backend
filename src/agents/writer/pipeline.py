"""Builds the Writer `CompiledGraph` — `write_section` self-loops via a
conditional edge (one section per pass, mirroring the Researcher's
round-loop), then falls through to `persist_draft` once the outline is
exhausted:

    write_section --(more sections)--> write_section
    write_section --(outline exhausted)--> persist_draft --> END

A second consecutive full-section failure inside `write_section` raises
rather than routing anywhere — `with_events` turns that into a `failed`
event and the exception propagates up to `Writer.run()`, same as any other
node failure in this codebase.
"""

from __future__ import annotations

from agents.writer.nodes.persist import make_persist_draft_node
from agents.writer.nodes.write_section import make_write_section_node, route_after_section
from db.repositories.writer_repository import WriterRepository
from graph.engine import END, CompiledGraph, Graph, NodeFn
from graph.events import EventEmitter, with_events
from llm.client import LLMClient


def build_writer_graph(
    llm_client: LLMClient,
    repo: WriterRepository,
    reasoning_effort: str | None = "medium",
    emitter: EventEmitter | None = None,
) -> CompiledGraph:
    def wrap(name: str, fn: NodeFn) -> NodeFn:
        return with_events(name, fn, emitter) if emitter is not None else with_events(name, fn)

    graph = Graph()
    graph.add_node("write_section", wrap("write_section", make_write_section_node(llm_client, reasoning_effort, emitter)))
    graph.add_node("persist_draft", wrap("persist_draft", make_persist_draft_node(repo)))

    graph.set_entry("write_section")
    graph.add_conditional_edge("write_section", route_after_section)
    graph.add_edge("persist_draft", END)

    return graph.compile()
