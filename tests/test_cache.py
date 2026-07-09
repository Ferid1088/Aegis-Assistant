import json
import pytest
import fakeredis
from unittest.mock import patch


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis()


def _patched_cache(fake_r):
    """Return the cached() helper with fake_redis injected."""
    import rag.capabilities.cache as c
    with patch.object(c, "_redis", fake_r):
        yield c.cached


@pytest.fixture
def cached(fake_redis):
    import rag.capabilities.cache as c
    original = c._redis
    c._redis = fake_redis
    yield c.cached
    c._redis = original


def test_cache_miss_calls_fn(cached):
    calls = []

    def fn():
        calls.append(1)
        return {"x": 42}

    result = cached("test", "key1", 60, fn)
    assert result == {"x": 42}
    assert len(calls) == 1


def test_cache_hit_skips_fn(cached):
    calls = []

    def fn():
        calls.append(1)
        return {"x": 42}

    cached("test", "key1", 60, fn)
    result = cached("test", "key1", 60, fn)
    assert result == {"x": 42}
    assert len(calls) == 1  # fn only called once


def test_cache_miss_when_redis_none():
    import rag.capabilities.cache as c
    original = c._redis
    c._redis = None
    calls = []

    def fn():
        calls.append(1)
        return {"x": 99}

    result = c.cached("test", "key1", 60, fn)
    assert result == {"x": 99}
    assert len(calls) == 1
    c._redis = original


def test_different_prefixes_are_independent(cached):
    calls = []

    def fn():
        calls.append(1)
        return calls[:]

    cached("a", "k", 60, fn)
    cached("b", "k", 60, fn)
    assert len(calls) == 2


def test_transform_query_cache_round_trip(fake_redis):
    """transform_query cache: same question returns cached dict without calling fn."""
    import rag.capabilities.cache as c
    original = c._redis
    c._redis = fake_redis

    calls = []

    def make_transform_fn(q):
        def fn():
            calls.append(q)
            return {"rewritten": q + "_rw", "expanded": q + "_ex", "lang": "de"}
        return fn

    q = "Was ist Urlaubsanspruch?"
    key = q
    r1 = c.cached("transform", key, 3600, make_transform_fn(q))
    r2 = c.cached("transform", key, 3600, make_transform_fn(q))

    assert r1 == r2
    assert len(calls) == 1  # fn only called once
    c._redis = original


def test_embed_dense_cache_round_trip(fake_redis):
    """embed_dense cache: same text+model returns cached vector."""
    import rag.capabilities.cache as c
    original = c._redis
    c._redis = fake_redis

    calls = []

    def embed_fn():
        calls.append(1)
        return [0.1, 0.2, 0.3]

    model = "BAAI/bge-m3"
    text = "Urlaubsanspruch"
    key = text + "|" + model

    v1 = c.cached("embed", key, 86400, embed_fn)
    v2 = c.cached("embed", key, 86400, embed_fn)

    assert v1 == [0.1, 0.2, 0.3]
    assert v2 == [0.1, 0.2, 0.3]
    assert len(calls) == 1
    c._redis = original
