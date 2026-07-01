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
