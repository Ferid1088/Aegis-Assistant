from datetime import datetime, timezone

from rag.crosscutting.security.time_utils import as_aware_utc


def test_naive_input_gets_utc_tzinfo_attached():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    result = as_aware_utc(naive)
    assert result.tzinfo == timezone.utc
    assert result == naive.replace(tzinfo=timezone.utc)


def test_aware_input_passes_through_unchanged():
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = as_aware_utc(aware)
    assert result is aware


def test_none_passes_through_as_none():
    assert as_aware_utc(None) is None
