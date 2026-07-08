"""Retrieval pipeline graph wiring."""

from langgraph.graph import END, START, StateGraph

from rag.pipelines.retrieval.state import QueryState, _checkpointer
from rag.pipelines.retrieval.nodes import (
    contextualize,
    _route_after_contextualize,
    cached_response,
    transform_query,
    retrieve_dense,
    retrieve_sparse,
    retrieve_graph,
    rrf_fuse,
    maybe_hyde,
    rerank,
    check_answerability,
    _route_answerability,
    gate_response,
    finalize_turn,
    generate,
    lifecycle_gate,
    _route_after_lifecycle,
    lifecycle_denied,
)


def build_query_graph():
    g = StateGraph(QueryState)
    g.add_node("lifecycle_gate", lifecycle_gate)
    g.add_node("lifecycle_denied", lifecycle_denied)
    g.add_node("contextualize", contextualize)
    g.add_node("cached_response", cached_response)
    g.add_node("transform_query", transform_query)
    g.add_node("retrieve_dense", retrieve_dense)
    g.add_node("retrieve_sparse", retrieve_sparse)
    g.add_node("retrieve_graph", retrieve_graph)
    g.add_node("rrf_fuse", rrf_fuse)
    g.add_node("maybe_hyde", maybe_hyde)
    g.add_node("rerank", rerank)
    g.add_node("check_answerability", check_answerability)
    g.add_node("gate_response", gate_response)
    g.add_node("generate", generate)
    g.add_node("finalize_turn", finalize_turn)

    g.add_edge(START, "lifecycle_gate")
    g.add_conditional_edges(
        "lifecycle_gate",
        _route_after_lifecycle,
        {"contextualize": "contextualize", "lifecycle_denied": "lifecycle_denied"},
    )
    g.add_edge("lifecycle_denied", END)
    g.add_conditional_edges(
        "contextualize",
        _route_after_contextualize,
        {
            "cached_response": "cached_response",
            "transform_query": "transform_query",
        },
    )
    g.add_edge("transform_query", "retrieve_dense")
    g.add_edge("transform_query", "retrieve_sparse")
    g.add_edge("transform_query", "retrieve_graph")
    g.add_edge("retrieve_dense", "rrf_fuse")
    g.add_edge("retrieve_sparse", "rrf_fuse")
    g.add_edge("retrieve_graph", "rrf_fuse")
    g.add_edge("rrf_fuse", "maybe_hyde")
    g.add_edge("maybe_hyde", "rerank")
    g.add_edge("rerank", "check_answerability")
    g.add_conditional_edges(
        "check_answerability",
        _route_answerability,
        {
            "generate": "generate",
            "gate_response": "gate_response",
        },
    )
    g.add_edge("generate", "finalize_turn")
    g.add_edge("gate_response", "finalize_turn")
    g.add_edge("cached_response", "finalize_turn")
    g.add_edge("finalize_turn", END)

    return g.compile(checkpointer=_checkpointer)
