"""Hardening gates for Incident 2.5 cross-team read/write boundaries."""
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2] / "app/views/incidents_view.py"


def test_service_context_enforces_per_service_permissions():
    source = VIEW.read_text(encoding="utf-8")
    read = source.split("def list_incident_affected_services(", 1)[1].split("\n\n@incidents_bp.route", 1)[0]
    add = source.split("def add_incident_affected_service(", 1)[1].split("\n\n@incidents_bp.route", 1)[0]
    remove = source.split("def remove_incident_affected_service(", 1)[1].split("\n\n# 2.5", 1)[0]
    assert "require_team_read(service.team_id)" in read
    assert "require_team_respond(service.team_id)" in add
    assert "require_team_respond(link.service.team_id)" in remove


def test_activity_scope_applied_before_fetching_technical_events():
    source = VIEW.read_text(encoding="utf-8")
    activity = source.split("def _incident_activity_rows(", 1)[1].split("\n\n@incidents_bp.route", 1)[0]
    assert "_visible_alert_group_links(incident)" in activity
    assert "AlertEvent.group.in_(visible_groups)" in activity
    assert "AlertComment.group.in_(visible_groups)" in activity
    assert "AlertComment.deleted == False" in activity
    assert "AlertComment.alert.is_null(True)" in activity


def test_external_links_only_allow_safe_web_urls():
    source = VIEW.read_text(encoding="utf-8")
    helper = source.split("def _safe_service_url(", 1)[1].split("\n\ndef ", 1)[0]
    assert '"http", "https"' in helper
    assert "parsed.username is not None" in helper
    assert "parsed.password is not None" in helper
    assert "parsed.port" in helper
