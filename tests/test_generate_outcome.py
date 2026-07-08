"""Test that _generate_impl records outcome on its span."""


def test_generate_impl_records_answered(monkeypatch):
    captured = {}

    def mock_set(key, value):
        captured[key] = value

    import rag.pipelines.retrieval.nodes as qmod
    import rag.crosscutting.observability.tracing as tr_module
    monkeypatch.setattr(tr_module, "set_span_attribute", mock_set)

    class FakeLLM:
        def invoke(self, prompt):
            class R:
                content = "Die Antwort ist 42."
            return R()

    monkeypatch.setattr(qmod, "get_llm", lambda: FakeLLM())

    from rag.domain.models import RetrievedChunk
    from rag.crosscutting.context import Context

    chunks = [RetrievedChunk(chunk_id="c1", content="text", score=0.9,
                             metadata={"page_numbers": [1]})]
    ctx = Context()
    result = qmod._generate_impl("Was ist 42?", chunks, lang="de", ctx=ctx)
    assert "answer" in result
    assert captured.get("outcome") == "answered"


def test_generate_impl_records_declined(monkeypatch):
    captured = {}

    def mock_set(key, value):
        captured[key] = value

    import rag.pipelines.retrieval.nodes as qmod
    import rag.crosscutting.observability.tracing as tr_module
    monkeypatch.setattr(tr_module, "set_span_attribute", mock_set)

    class FakeLLM:
        def invoke(self, prompt):
            class R:
                content = "Die Antwort ist nicht im kontext enthalten."
            return R()

    monkeypatch.setattr(qmod, "get_llm", lambda: FakeLLM())

    from rag.domain.models import RetrievedChunk
    from rag.crosscutting.context import Context

    chunks = [RetrievedChunk(chunk_id="c1", content="text", score=0.9,
                             metadata={"page_numbers": [1]})]
    ctx = Context()
    qmod._generate_impl("Was?", chunks, lang="de", ctx=ctx)
    assert captured.get("outcome") == "declined"


def test_generate_impl_records_retrieval_miss(monkeypatch):
    captured = {}

    def mock_set(key, value):
        captured[key] = value

    import rag.pipelines.retrieval.nodes as qmod
    import rag.crosscutting.observability.tracing as tr_module
    monkeypatch.setattr(tr_module, "set_span_attribute", mock_set)

    class FakeLLM:
        def invoke(self, prompt):
            class R:
                content = "Keine Information."
            return R()

    monkeypatch.setattr(qmod, "get_llm", lambda: FakeLLM())

    from rag.crosscutting.context import Context

    ctx = Context()
    # Empty reranked list → retrieval_miss
    qmod._generate_impl("Was?", [], lang="de", ctx=ctx)
    assert captured.get("retrieval_miss") is True


def test_generate_impl_records_fallback(monkeypatch):
    captured = {}

    def mock_set(key, value):
        captured[key] = value

    import rag.pipelines.retrieval.nodes as qmod
    import rag.crosscutting.observability.tracing as tr_module
    monkeypatch.setattr(tr_module, "set_span_attribute", mock_set)

    class FakeLLM:
        def invoke(self, prompt):
            class R:
                content = "Synthesized answer."
            return R()

    monkeypatch.setattr(qmod, "get_llm", lambda: FakeLLM())

    from rag.domain.models import RetrievedChunk
    from rag.crosscutting.context import Context

    chunks = [RetrievedChunk(chunk_id="c1", content="text", score=0.9,
                             metadata={"page_numbers": [1]})]
    ctx = Context()
    step_results = [{"step": 1, "sub_question": "sub?", "answer": "42"}]
    qmod._generate_impl("Was?", chunks, lang="de", step_results=step_results, ctx=ctx)
    assert captured.get("outcome") == "fallback"
