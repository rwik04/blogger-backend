"""A minimal, dependency-free graph/state-machine engine.

Deliberately not LangGraph: nodes are plain async functions over a shared
mutable `state` dict, edges (including conditional edges that can loop back
"up" the graph, and a fan-out helper for bounded-concurrency branches) are
declared on a `Graph` builder, and `Graph.compile()` returns a `CompiledGraph`
that walks nodes until it hits `END`.

Usage:
    graph = Graph()
    graph.add_node("plan", plan_fn)
    graph.add_fanout_node("search", search_one, items_key="queries", result_key="hits")
    graph.add_node("filter", filter_fn)
    graph.set_entry("plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "filter")
    graph.add_conditional_edge("filter", router_fn)

    result_state = await graph.compile().arun(initial_state)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

END = "__end__"

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
RouterFn = Callable[[dict[str, Any]], str]
ItemFn = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class FanoutSpec:
    item_fn: ItemFn
    items_key: str
    result_key: str
    max_concurrency: int


class GraphError(Exception):
    """Raised for graph construction/execution errors (unknown nodes, missing entry, etc)."""


class Graph:
    """Builder for a node/edge graph. Call `.compile()` to get a runnable."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._conditional_edges: dict[str, RouterFn] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: NodeFn) -> None:
        if name == END:
            raise GraphError(f"'{END}' is reserved and cannot be used as a node name")
        self._nodes[name] = fn

    def add_fanout_node(
        self,
        name: str,
        item_fn: ItemFn,
        *,
        items_key: str,
        result_key: str,
        max_concurrency: int = 3,
    ) -> None:
        """Registers a node that runs `item_fn` once per element of `state[items_key]`,
        concurrently, bounded by `max_concurrency`, and stores the collected results
        (exceptions filtered out and logged, not raised) under `state[result_key]`.

        This is the engine's replacement for LangGraph's `Send` API — from the
        engine's point of view it's still a single node with one execution.
        """
        self._nodes[name] = build_fanout_node(
            name, item_fn, items_key=items_key, result_key=result_key, max_concurrency=max_concurrency
        )

    def set_entry(self, name: str) -> None:
        self._entry = name

    def add_edge(self, src: str, dst: str) -> None:
        self._edges[src] = dst

    def add_conditional_edge(self, src: str, router: RouterFn) -> None:
        """`router(state) -> next_node_name`. The router may mutate `state` in
        place (e.g. to stage the next round's inputs before looping back to an
        earlier node) — it receives the actual state object, not a copy.
        """
        self._conditional_edges[src] = router

    def compile(self) -> "CompiledGraph":
        if self._entry is None:
            raise GraphError("Graph has no entry point; call set_entry() first")
        if self._entry not in self._nodes:
            raise GraphError(f"Entry point '{self._entry}' is not a registered node")
        return CompiledGraph(self)


def build_fanout_node(
    name: str,
    item_fn: ItemFn,
    *,
    items_key: str,
    result_key: str,
    max_concurrency: int = 3,
) -> NodeFn:
    """Builds a fan-out node function without registering it — exposed publicly
    so callers can wrap it (e.g. with `graph.events.with_events`) before adding
    it to a `Graph` via `add_node`, the same as any other node. `add_fanout_node`
    uses this internally for the common case where no wrapping is needed.
    """
    spec = FanoutSpec(item_fn, items_key, result_key, max_concurrency)

    async def run(state: dict[str, Any]) -> dict[str, Any]:
        items = state.get(spec.items_key) or []
        semaphore = asyncio.Semaphore(spec.max_concurrency)

        async def bounded(item: Any) -> dict[str, Any]:
            async with semaphore:
                return await spec.item_fn(item, state)

        raw_results = await asyncio.gather(*(bounded(item) for item in items), return_exceptions=True)
        results: list[dict[str, Any]] = []
        for item, result in zip(items, raw_results):
            if isinstance(result, Exception):
                logger.warning("Fan-out item failed in node '%s' (item=%r): %s", name, item, result)
                continue
            results.append(result)
        return {spec.result_key: results}

    return run


class CompiledGraph:
    def __init__(self, graph: Graph) -> None:
        self._graph = graph

    async def arun(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        state = dict(initial_state)
        current: str | None = self._graph._entry

        while current is not None and current != END:
            if current not in self._graph._nodes:
                raise GraphError(f"Unknown node '{current}' reached during execution")

            fn = self._graph._nodes[current]
            update = await fn(state)
            if update:
                state.update(update)

            if current in self._graph._conditional_edges:
                current = self._graph._conditional_edges[current](state)
            elif current in self._graph._edges:
                current = self._graph._edges[current]
            else:
                current = None  # no outgoing edge — treat as implicit terminal node

        return state
