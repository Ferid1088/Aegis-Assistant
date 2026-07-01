"""Simple Gradio chat UI for the RAG pipeline."""

import uuid

import gradio as gr

from rag.graphs.query import build_query_graph

graph = build_query_graph()


def chat(message, history, conversation_id):
    conversation_id = conversation_id or str(uuid.uuid4())
    result = graph.invoke(
        {"question": message, "conversation_id": conversation_id},
        config={"configurable": {"thread_id": conversation_id}},
    )
    answer = result.get("answer", "No answer generated")
    citations = result.get("citations", [])

    if citations:
        cite_lines = []
        for i, c in enumerate(citations[:5]):
            pages = c.get("page_numbers", [])
            section = c.get("section", [])
            cite_lines.append(f"[{i+1}] pages={pages}  section={section}")
        answer += "\n\n---\n**Sources:**\n" + "\n".join(cite_lines)

    return answer, conversation_id


conversation_state = gr.State("")


demo = gr.ChatInterface(
    fn=chat,
    additional_inputs=conversation_state,
    additional_outputs=conversation_state,
    title="Aegis Assistant — Document RAG",
    description="Ask grounded questions about your ingested documents",
    examples=[
        "Was verdient E12 in Stufe 4?",
        "Welche Unterschiede gibt es zwischen E 9 und KR 9a?",
        "Fasse die wichtigsten Aussagen des Dokuments zusammen.",
    ],
)

if __name__ == "__main__":
    demo.launch()
