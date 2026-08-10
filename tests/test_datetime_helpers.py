from datetime import datetime, timedelta, timezone

from app.modules.common import (
    as_utc_naive,
    as_utc_naive_seconds,
    local_datetime_to_utc_naive,
    utc_datetime_to_local_naive,
    utc_now_seconds,
)


def test_as_utc_naive_preserves_naive_utc_wall_clock_and_microseconds():
    value = datetime(2026, 8, 10, 12, 34, 56, 789123)

    result = as_utc_naive(value)

    assert result == value
    assert result.tzinfo is None
    assert result.microsecond == 789123


def test_as_utc_naive_converts_aware_datetime_to_utc():
    value = datetime(
        2026,
        8,
        10,
        12,
        34,
        56,
        123456,
        tzinfo=timezone(timedelta(hours=3)),
    )

    result = as_utc_naive(value)

    assert result == datetime(2026, 8, 10, 9, 34, 56, 123456)
    assert result.tzinfo is None


def test_as_utc_naive_accepts_z_and_offset_iso_strings():
    assert as_utc_naive("2026-08-10T09:34:56Z") == datetime(
        2026,
        8,
        10,
        9,
        34,
        56,
    )
    assert as_utc_naive("2026-08-10T12:34:56+03:00") == datetime(
        2026,
        8,
        10,
        9,
        34,
        56,
    )


def test_as_utc_naive_returns_none_for_none_and_blank_string():
    assert as_utc_naive(None) is None
    assert as_utc_naive("") is None
    assert as_utc_naive("   ") is None


def test_as_utc_naive_seconds_truncates_only_microseconds():
    value = datetime(
        2026,
        8,
        10,
        12,
        34,
        56,
        789123,
        tzinfo=timezone(timedelta(hours=3)),
    )

    result = as_utc_naive_seconds(value)

    assert result == datetime(2026, 8, 10, 9, 34, 56)
    assert result.tzinfo is None
    assert result.microsecond == 0


def test_utc_now_seconds_returns_naive_utc_whole_seconds():
    before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    result = utc_now_seconds()
    after = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)

    assert before <= result <= after
    assert result.tzinfo is None
    assert result.microsecond == 0


def test_local_datetime_to_utc_naive_uses_named_timezone():
    value = datetime(2026, 6, 1, 0, 0, 0)

    assert local_datetime_to_utc_naive(value, "Europe/Moscow") == datetime(
        2026, 5, 31, 21, 0, 0
    )


def test_utc_datetime_to_local_naive_uses_named_timezone():
    value = datetime(2026, 5, 31, 21, 0, 0)

    assert utc_datetime_to_local_naive(value, "Europe/Moscow") == datetime(
        2026, 6, 1, 0, 0, 0
    )
