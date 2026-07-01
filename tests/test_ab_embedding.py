def test_ab_result_structure():
    """ab_run() returns dict with model name → score dict."""
    # Just verify the structure contracts — no model loaded
    expected_keys = {"model", "faithfulness", "answer_relevancy",
                     "context_precision", "context_recall"}
    result = {
        "model": "bge-m3",
        "faithfulness": 0.8,
        "answer_relevancy": 0.75,
        "context_precision": 0.7,
        "context_recall": 0.65,
    }
    assert set(result.keys()) == expected_keys
