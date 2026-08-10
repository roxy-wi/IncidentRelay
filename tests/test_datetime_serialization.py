from datetime import datetime, timedelta, timezone

from app.services.serializers.common import serialize_utc_datetime


def test_serialize_utc_datetime_marks_naive_values_as_utc():
    value = datetime(2026, 8, 10, 9, 34, 56, 123456)

    assert serialize_utc_datetime(value) == "2026-08-10T09:34:56.123456Z"


def test_serialize_utc_datetime_converts_aware_values_to_utc():
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

    assert serialize_utc_datetime(value) == "2026-08-10T09:34:56.123456Z"


def test_serialize_utc_datetime_accepts_iso_strings():
    assert (
        serialize_utc_datetime("2026-08-10T12:34:56+03:00")
        == "2026-08-10T09:34:56Z"
    )


def test_serialize_utc_datetime_returns_none_for_empty_values():
    assert serialize_utc_datetime(None) is None
    assert serialize_utc_datetime("") is None
