def test_ab_extraction_result_keys():
    expected = {"model", "entity_drop_rate", "relation_drop_rate",
                "ragas_recall", "seconds_per_chunk"}
    record = {
        "model": "qwen2.5:7b",
        "entity_drop_rate": 0.05,
        "relation_drop_rate": 0.08,
        "ragas_recall": 0.72,
        "seconds_per_chunk": 4.2,
    }
    assert set(record.keys()) == expected
