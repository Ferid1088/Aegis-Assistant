from datetime import datetime, timedelta, timezone

from rag.config import settings
from rag.auth.lockout import apply_failed_attempt, is_locked


def test_is_locked_false_when_locked_until_is_none():
    assert is_locked(None) is False


def test_is_locked_true_when_locked_until_in_future():
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert is_locked(future) is True


def test_is_locked_false_when_locked_until_in_past():
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert is_locked(past) is False


def test_apply_failed_attempt_below_threshold_does_not_lock():
    new_count, locked_until, reason = apply_failed_attempt(settings.lockout_threshold - 2)
    assert new_count == settings.lockout_threshold - 1
    assert locked_until is None
    assert reason is None


def test_apply_failed_attempt_at_threshold_locks():
    new_count, locked_until, reason = apply_failed_attempt(settings.lockout_threshold - 1)
    assert new_count == settings.lockout_threshold
    assert locked_until is not None
    assert locked_until > datetime.now(timezone.utc)
    assert reason == "too many failed login attempts"
