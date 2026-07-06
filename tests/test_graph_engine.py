import pytest

from graph.engine import END, Graph, GraphError


async def test_linear_graph_runs_nodes_in_order():
    graph = Graph()

    async def step_one(state):
        return {"trace": state.get("trace", []) + ["one"]}

    async def step_two(state):
        return {"trace": state.get("trace", []) + ["two"]}

    graph.add_node("one", step_one)
    graph.add_node("two", step_two)
    graph.set_entry("one")
    graph.add_edge("one", "two")
    graph.add_edge("two", END)

    result = await graph.compile().arun({})
    assert result["trace"] == ["one", "two"]


async def test_conditional_edge_can_loop_back():
    graph = Graph()

    async def increment(state):
        return {"count": state.get("count", 0) + 1}

    def router(state):
        return "increment" if state["count"] < 3 else END

    graph.add_node("increment", increment)
    graph.set_entry("increment")
    graph.add_conditional_edge("increment", router)

    result = await graph.compile().arun({})
    assert result["count"] == 3


async def test_fanout_runs_items_concurrently_and_collects_results():
    graph = Graph()

    async def double(item, _state):
        return {"value": item * 2}

    graph.add_fanout_node("double_all", double, items_key="items", result_key="doubled")
    graph.set_entry("double_all")

    result = await graph.compile().arun({"items": [1, 2, 3]})
    assert sorted(r["value"] for r in result["doubled"]) == [2, 4, 6]


async def test_fanout_drops_failed_items_without_raising():
    graph = Graph()

    async def maybe_fail(item, _state):
        if item == "bad":
            raise ValueError("boom")
        return {"value": item}

    graph.add_fanout_node("run", maybe_fail, items_key="items", result_key="results")
    graph.set_entry("run")

    result = await graph.compile().arun({"items": ["good", "bad"]})
    assert result["results"] == [{"value": "good"}]


def test_compile_requires_entry_point():
    graph = Graph()
    graph.add_node("a", lambda state: state)

    with pytest.raises(GraphError):
        graph.compile()
