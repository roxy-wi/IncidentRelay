"""Static security contract checks for the cross-domain Incident activity read model.

The runtime API coverage belongs to the Incident test suite; these checks also
catch accidental removal of the per-source authorization and attribution rules.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEW = ROOT / "app/views/incidents_view.py"
OPENAPI = ROOT / "app/api/openapi/endpoints/incidents.py"


def test_combined_activity_preserves_provenance_and_scoped_links():
    source = VIEW.read_text(encoding="utf-8")
    activity = source.split("def _incident_activity_rows(", 1)[1]
    assert '"source_type": "Incident"' in activity
    assert '"source_type": "AlertGroup"' in activity
    assert '"target_id":' in activity
    assert '"actor_id":' in activity
    assert "incident_core_repo.list_active_links(incident.id)" in activity
    assert "require_team_read(group.team_id)" in activity
    assert "is_admin_user(_request_user())" in activity
    assert "AlertComment.deleted == False" in activity
    assert "AlertComment.alert.is_null(True)" in activity
    assert '"_sort_at"' in activity


def test_combined_activity_is_read_only_and_documented():
    view = VIEW.read_text(encoding="utf-8")
    assert '@incidents_bp.route("/<int:incident_id>/activity", methods=["GET"])' in view
    assert 'if not 1 <= limit <= 500:' in view
    spec = OPENAPI.read_text(encoding="utf-8")
    assert '"/api/incidents/{incident_id}/activity":' in spec
    assert '"summary": "Combined Incident and authorized linked AlertGroup activity"' in spec
    assert '"source_type": {"type": "string", "enum": ["Incident", "AlertGroup"]}' in spec


def test_link_visibility_is_shared_by_detail_and_link_collection():
    source = VIEW.read_text(encoding="utf-8")
    helper = source.split("def _visible_alert_group_links(", 1)[1].split("\n\ndef ", 1)[0]
    assert "require_team_read(group.team_id)" in helper
    assert "is_admin_user(_request_user())" in helper
    assert 'payload["alert_groups"] = [serialize_incident_link(link) for link in _visible_alert_group_links(incident)]' in source
    assert 'return jsonify([serialize_incident_link(link) for link in _visible_alert_group_links(incident)])' in source


def test_unlink_checks_technical_group_scope_before_mutating():
    source = VIEW.read_text(encoding="utf-8")
    section = source.split("def unlink_incident_alert_group(", 1)[1].split("\n\n@incidents_bp.route", 1)[0]
    assert "require_team_respond(group.team_id)" in section
    assert "is_admin_user(_request_user())" in section
    assert section.index("require_team_respond(group.team_id)") < section.index("unlink_alert_group(")
