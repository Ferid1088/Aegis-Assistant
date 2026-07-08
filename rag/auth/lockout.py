from datetime import datetime, timedelta, timezone

from rag.config import settings


def is_locked(locked_until: datetime | None) -> bool:
    if locked_until is None:
        return False
    return datetime.now(timezone.utc) < locked_until


def apply_failed_attempt(failed_login_count: int) -> tuple[int, datetime | None, str | None]:
    """Pure function. Given the count BEFORE this attempt, returns
    (new_count, locked_until, lock_reason). The latter two are None unless
    this attempt just crossed the lockout threshold."""
    new_count = failed_login_count + 1
    if new_count >= settings.lockout_threshold:
        locked_until = datetime.now(timezone.utc) + timedelta(seconds=settings.lockout_duration_seconds)
        return new_count, locked_until, "too many failed login attempts"
    return new_count, None, None
