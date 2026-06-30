"""Simple Gradio chat UI for the RAG pipeline."""

import gradio as gr

from rag.graphs.query import build_query_graph

graph = build_query_graph()


def chat(message, history):
    result = graph.invoke({"question": message})
    answer = result.get("answer", "No answer generated")
    citations = result.get("citations", [])

    if citations:
        cite_lines = []
        for i, c in enumerate(citations[:5]):
            pages = c.get("page_numbers", [])
            section = c.get("section", [])
            cite_lines.append(f"[{i+1}] pages={pages}  section={section}")
        answer += "\n\n---\n**Sources:**\n" + "\n".join(cite_lines)

    return answer


demo = gr.ChatInterface(
    fn=chat,
    title="Aegis Assistant — TV-L RAG",
    description="Ask questions about the Tarifvertrag der Länder (TV-L)",
    examples=[
        "Was verdient E12 in Stufe 4?",
        "Werden Pflegekräfte benachteiligt?",
        "Welche Anforderungen hat Entgeltgruppe 9?",
    ],
)

if __name__ == "__main__":
    demo.launch()
