from functools import lru_cache
from typing import Generator

import numpy as np
from fastembed import SparseTextEmbedding
from langchain_ollama import ChatOllama
from sentence_transformers import SentenceTransformer

from rag.config import settings


def get_device() -> str:
    if settings.device:
        return settings.device
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class DenseEmbedder:
    """Wraps SentenceTransformer to provide .embed() matching the fastembed API."""

    def __init__(self, model_name: str) -> None:
        self._model = SentenceTransformer(model_name, device=get_device())

    def embed(self, texts: list[str], prefix: str = "") -> Generator[np.ndarray, None, None]:
        if prefix:
            texts = [prefix + t for t in texts]
        vectors = self._model.encode(texts, normalize_embeddings=True)
        yield from vectors


@lru_cache(maxsize=1)
def get_embedder() -> DenseEmbedder:
    return DenseEmbedder(settings.dense_embedding_model)


@lru_cache(maxsize=1)
def get_sparse_embedder() -> SparseTextEmbedding:
    return SparseTextEmbedding(model_name=settings.sparse_embedding_model)


def _make_chat(model: str, temperature: float):
    if settings.llm_backend == "vllm":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            base_url=settings.vllm_base_url,
            api_key="EMPTY",
            temperature=temperature,
            max_tokens=settings.max_generation_tokens,
        )
    return ChatOllama(
        model=model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        num_predict=settings.max_generation_tokens,
    )


@lru_cache(maxsize=1)
def get_llm():
    return _make_chat(settings.llm_model, settings.temperature)


@lru_cache(maxsize=1)
def get_extraction_llm():
    return _make_chat(settings.extraction_model, 0.0)
