"""CLI entry point for the query pipeline."""

import argparse
import json

from rag.graphs.query import build_query_graph


def main():
    parser = argparse.ArgumentParser(description="Query the RAG pipeline")
    parser.add_argument("question", type=str, help="Question to ask")
    parser.add_argument("--doc-filter", type=str, default=None, help="JSON doc filter")
    args = parser.parse_args()

    graph = build_query_graph()
    state = {"question": args.question}
    if args.doc_filter:
        state["doc_filter"] = json.loads(args.doc_filter)

    result = graph.invoke(state)

    print("\n" + "=" * 60)
    print("ANSWER:")
    print("=" * 60)
    print(result.get("answer", "No answer generated"))

    citations = result.get("citations", [])
    if citations:
        print("\n" + "-" * 60)
        print("CITATIONS:")
        print("-" * 60)
        for i, c in enumerate(citations):
            pages = c.get("page_numbers", [])
            section = c.get("section", [])
            print(f"  [{i + 1}] pages={pages}  section={section}")
            for bb in c.get("bboxes", []):
                print(f"      bbox: page={bb['page']}, x={bb['x']:.0f}, y={bb['y']:.0f}, "
                      f"w={bb['width']:.0f}, h={bb['height']:.0f}")


if __name__ == "__main__":
    main()
