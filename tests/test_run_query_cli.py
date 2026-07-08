"""Regression test for a real bug in run_query.py (repo-root CLI entry point):
build_query_graph() (rag/pipelines/retrieval/graph.py) always compiles the graph with a
checkpointer attached (`g.compile(checkpointer=_checkpointer)`), and LangGraph
requires a `configurable.thread_id` (or checkpoint_ns/checkpoint_id) on every
`.invoke()` once a checkpointer is present, or it raises
`ValueError("Checkpointer requires one or more of the following 'configurable'
keys: thread_id, checkpoint_ns, checkpoint_id")`.

run_query.py called `graph.invoke(state)` with no `config` at all, so every
single invocation of the CLI crashed outright with that uncaught ValueError.
Confirmed by reverting the fix and running `uv run python run_query.py
"test"`, which raised exactly that ValueError.

The identical bug was already found and fixed in eval/run_eval.py (each golden
question gets its own `thread_id=f"eval-{i}"`, since no cross-turn state is
needed for a one-shot query). run_query.py is a single one-shot CLI
invocation (not a loop), so the fix uses a fresh `uuid.uuid4()` thread_id per
invocation instead, so repeated invocations don't collide on shared
checkpointer state.

This test mocks build_query_graph()'s return value (a fake compiled graph)
and asserts main() invokes it with a `config={"configurable": {"thread_id":
...}}` kwarg carrying a non-empty thread_id -- proving the fix without
needing real Qdrant data, an LLM, or embedding models.
"""
import sys
from unittest.mock import MagicMock, patch


@patch("run_query.build_query_graph")
def test_main_passes_thread_id_config_to_graph_invoke(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {"answer": "the answer", "citations": []}
    mock_build_graph.return_value = mock_graph

    import run_query

    with patch.object(sys, "argv", ["run_query.py", "What is this about?"]):
        run_query.main()

    mock_graph.invoke.assert_called_once()
    args, kwargs = mock_graph.invoke.call_args

    assert args[0] == {"question": "What is this about?"}

    config = kwargs.get("config")
    assert config is not None, (
        "graph.invoke() must be called with a `config` kwarg -- "
        "build_query_graph() always compiles with a checkpointer attached, "
        "and LangGraph raises ValueError without a thread_id in configurable"
    )
    thread_id = config.get("configurable", {}).get("thread_id")
    assert thread_id, "config['configurable']['thread_id'] must be a non-empty value"


@patch("run_query.build_query_graph")
def test_main_uses_a_fresh_thread_id_per_invocation(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {"answer": "ans", "citations": []}
    mock_build_graph.return_value = mock_graph

    import run_query

    with patch.object(sys, "argv", ["run_query.py", "q1"]):
        run_query.main()
    with patch.object(sys, "argv", ["run_query.py", "q2"]):
        run_query.main()

    first_call, second_call = mock_graph.invoke.call_args_list
    first_thread_id = first_call.kwargs["config"]["configurable"]["thread_id"]
    second_thread_id = second_call.kwargs["config"]["configurable"]["thread_id"]

    assert first_thread_id != second_thread_id, (
        "each CLI invocation should get its own unique thread_id so repeated "
        "invocations don't collide on shared checkpointer state"
    )
