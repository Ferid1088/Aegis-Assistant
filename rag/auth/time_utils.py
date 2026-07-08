from datetime import datetime, timezone


def as_aware_utc(value: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime to UTC-aware.

    SQLite's DateTime(timezone=True) columns round-trip as timezone-naive
    (unlike Postgres, which preserves tzinfo) — this re-labels a naive
    value as UTC without converting it, since values in this codebase are
    always constructed as UTC-aware before being persisted. Already-aware
    values pass through unchanged.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)
