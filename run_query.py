"""CLI entry point for the query pipeline."""

import argparse
import json
import uuid

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

    # build_query_graph() always compiles with a checkpointer attached
    # (rag/graphs/query.py's _make_checkpointer(), InMemorySaver or
    # SqliteSaver) -- LangGraph requires a configurable.thread_id (or
    # checkpoint_ns/checkpoint_id) on every .invoke() once a checkpointer is
    # present, or it raises ValueError("Checkpointer requires one or more of
    # the following 'configurable' keys..."). This is a one-shot CLI
    # invocation (no cross-turn state to preserve, unlike the real API route
    # which reuses a conversation_id across turns), so a fresh unique
    # thread_id per invocation is enough to satisfy the requirement without
    # colliding with other invocations on shared checkpointer state. Same fix
    # already applied to eval/run_eval.py for the identical reason.
    result = graph.invoke(
        state, config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

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
