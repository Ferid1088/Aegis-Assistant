"""CLI entry point for the ingestion pipeline."""

import argparse
from pathlib import Path

from rag.graphs.ingestion import build_ingestion_graph


def main():
    parser = argparse.ArgumentParser(description="Ingest a PDF into the RAG pipeline")
    parser.add_argument("file", type=Path, help="Path to the PDF file")
    parser.add_argument("--version", type=str, default=None, help="Document version label")
    args = parser.parse_args()

    if not args.file.exists():
        parser.error(f"File not found: {args.file}")

    graph = build_ingestion_graph()
    state = {"file_path": str(args.file)}
    if args.version:
        state["doc_version"] = args.version

    result = graph.invoke(state)
    print(f"\nResult: {result.get('status', 'unknown')}")
    if result.get("indexed_count"):
        print(f"Chunks indexed: {result['indexed_count']}")


if __name__ == "__main__":
    main()
