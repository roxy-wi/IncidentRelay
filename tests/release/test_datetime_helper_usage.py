from pathlib import Path


FILES_WITH_SHARED_UTC_NORMALIZATION = {
    "app/services/oncall.py": ("def _as_utc_naive",),
    "app/services/oncall_health.py": ("def as_utc_naive", "def utc_now_naive"),
    "app/services/calendar_service.py": ("def as_utc_naive",),
    "app/views/calendar_view.py": ("def _as_utc_naive",),
    "app/services/notifications/shift_notifications.py": ("def _event_dt",),
    "app/views/business_services/routes.py": ("def normalize_optional_utc_datetime",),
    "app/services/heartbeats/service.py": ("def _as_naive_utc", "def _utcnow"),
    "app/services/user_oncall_status.py": ("def _utc_naive_now",),
    "app/modules/db/orchestrations_repo.py": ("def _utcnow",),
}


def test_common_naive_utc_normalization_is_not_reimplemented_locally():
    leftovers = {}

    for filename, forbidden_snippets in FILES_WITH_SHARED_UTC_NORMALIZATION.items():
        source = Path(filename).read_text(encoding="utf-8")
        found = [snippet for snippet in forbidden_snippets if snippet in source]
        if found:
            leftovers[filename] = found

    assert leftovers == {}
