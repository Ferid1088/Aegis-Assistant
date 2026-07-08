"""Ingestion pipeline graph wiring."""

from langgraph.graph import END, START, StateGraph

from rag.pipelines.ingestion.state import IngestionState
from rag.pipelines.ingestion.nodes import convert, chunk_and_index, extract_graph_artifacts


# ── Graph ────────────────────────────────────────────────────────────────

def build_ingestion_graph():
    g = StateGraph(IngestionState)
    g.add_node("convert", convert)
    g.add_node("chunk_and_index", chunk_and_index)
    g.add_node("extract_graph_artifacts", extract_graph_artifacts)
    g.add_edge(START, "convert")
    g.add_edge("convert", "chunk_and_index")
    g.add_edge("chunk_and_index", "extract_graph_artifacts")
    g.add_edge("extract_graph_artifacts", END)
    return g.compile()
