"""Incident 2.5 service context browser-link safety regression tests."""

import pytest

from app.views.incidents_view import _safe_service_url


@pytest.mark.parametrize("value, expected", [
    ("https://example.org/runbook", "https://example.org/runbook"),
    (" http://example.org/dashboard ", "http://example.org/dashboard"),
    ("javascript:alert(1)", None),
    ("data:text/html,bad", None),
    ("//example.org", None),
    ("/relative/path", None),
    ("https://", None),
    (None, None),
    ("https://user:password@example.org/private", None),
    ("https://example.org/path\nmalicious", None),
    ("https://example.org/path\tmalicious", None),
    ("https://example.org:badport/runbook", None),
])
def test_incident_service_context_emits_only_http_urls(value, expected):
    assert _safe_service_url(value) == expected
