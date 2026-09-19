"""Regression guards for the Incident Management v2 AlertGroup API split."""

from pathlib import Path


APP_INIT = Path("app/__init__.py").read_text(encoding="utf-8")
ALERTS_VIEW = Path("app/views/alerts_view.py").read_text(encoding="utf-8")
ALERTS_PAGE = Path("app/static/js/pages/alerts.js").read_text(encoding="utf-8")
ALERT_COMMENTS = Path(
    "app/static/js/components/alerts/alerts_comment.js"
).read_text(encoding="utf-8")
DASHBOARD = Path("app/static/js/pages/dashboard.js").read_text(encoding="utf-8")


def test_alert_group_api_is_registered_at_the_2_3_contract_path():
    assert 'url_prefix="/api/alert-groups"' in APP_INIT
    assert 'url_prefix="/api/alerts"' not in APP_INIT
    assert '@alerts_bp.route("/<int:alert_id>/acknowledge"' in ALERTS_VIEW
    assert '@alerts_bp.route("/<int:target_group_id>/merge"' in ALERTS_VIEW
    assert '@alerts_bp.route("/<int:alert_id>/ack"' not in ALERTS_VIEW
    assert '@alerts_bp.route("/merge"' not in ALERTS_VIEW


def test_frontend_uses_alert_group_api_without_changing_browser_routes():
    frontend_sources = (ALERTS_PAGE, ALERT_COMMENTS, DASHBOARD)

    for source in frontend_sources:
        assert "/api/alerts" not in source

    assert "/api/alert-groups" in ALERTS_PAGE
    assert "/api/alert-groups" in ALERT_COMMENTS
    assert "/api/alert-groups" in DASHBOARD
    assert (
        'apiPost("/api/alert-groups/" + currentDetailsAlertId + "/acknowledge"'
        in ALERTS_PAGE
    )
    assert 'apiPost("/api/alert-groups/" + targetId + "/merge"' in ALERTS_PAGE
    assert (
        'apiPost("/api/alert-groups/" + alert.id + "/acknowledge"'
        in DASHBOARD
    )
    assert (
        'return "/alerts/" + encodeURIComponent(alertId) + query;'
        in ALERTS_PAGE
    )
