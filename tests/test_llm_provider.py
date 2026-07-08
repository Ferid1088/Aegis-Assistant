from unittest.mock import patch

from rag.config import settings
from rag.infra.models.llm import _make_chat


@patch("langchain_openai.ChatOpenAI")
def test_make_chat_passes_timeout_to_chatopenai_for_vllm_backend(mock_chat_openai, monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "vllm")
    monkeypatch.setattr(settings, "llm_request_timeout_seconds", 45)

    _make_chat("qwen2.5:7b", 0.1)

    _, kwargs = mock_chat_openai.call_args
    assert kwargs["timeout"] == 45


@patch("rag.infra.models.llm.ChatOllama")
def test_make_chat_passes_timeout_to_chatollama_for_ollama_backend(mock_chat_ollama, monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "ollama")
    monkeypatch.setattr(settings, "llm_request_timeout_seconds", 45)

    _make_chat("qwen2.5:7b", 0.1)

    _, kwargs = mock_chat_ollama.call_args
    assert kwargs["client_kwargs"] == {"timeout": 45}
