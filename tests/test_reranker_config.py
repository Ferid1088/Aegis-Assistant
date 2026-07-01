from unittest.mock import MagicMock, patch


def test_get_reranker_passes_fp16_flag():
    import torch
    import rag.graphs.query as q
    q._reranker = None

    with patch("rag.graphs.query.CrossEncoder") as MockCE, \
         patch("rag.graphs.query.settings") as mock_s, \
         patch("rag.graphs.query.get_device", return_value="cpu"):
        mock_s.reranker_model = "BAAI/bge-reranker-v2-m3"
        mock_s.reranker_use_fp16 = True
        MockCE.return_value = MagicMock()

        q._get_reranker()

        call_kwargs = MockCE.call_args[1]
        assert "model_kwargs" in call_kwargs
        assert call_kwargs["model_kwargs"]["torch_dtype"] == torch.float16
    q._reranker = None


def test_get_reranker_no_fp16_by_default():
    import rag.graphs.query as q
    q._reranker = None

    with patch("rag.graphs.query.CrossEncoder") as MockCE, \
         patch("rag.graphs.query.settings") as mock_s, \
         patch("rag.graphs.query.get_device", return_value="cpu"):
        mock_s.reranker_model = "BAAI/bge-reranker-v2-m3"
        mock_s.reranker_use_fp16 = False
        MockCE.return_value = MagicMock()

        q._get_reranker()

        call_kwargs = MockCE.call_args[1]
        assert "use_half_precision" not in call_kwargs or call_kwargs["use_half_precision"] is False
    q._reranker = None


def test_rerank_impl_uses_batch_size():
    """_rerank_impl passes batch_size to predict()."""
    import rag.graphs.query as q
    from rag.models import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id="c1", content="text", score=0.5,
        metadata={"page_numbers": [1], "heading_path": [], "bboxes": []},
    )
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [0.9]

    with patch("rag.graphs.query._get_reranker", return_value=mock_reranker), \
         patch("rag.graphs.query.settings") as mock_s:
        mock_s.reranker_batch_size = 16
        mock_s.rerank_top_k = 10
        q._rerank_impl("question", [chunk])

    mock_reranker.predict.assert_called_once()
    call_kwargs = mock_reranker.predict.call_args[1]
    assert call_kwargs.get("batch_size") == 16
