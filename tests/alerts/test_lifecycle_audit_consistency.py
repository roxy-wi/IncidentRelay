"""Canonical alert-group audit generated in the service, not HTTP transport."""
from app.modules.db.models import AuditLog, AlertEvent
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.modules.db.models import AlertGroup
from tests.factories import create_group, create_team, create_route, unique


def _scope():
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    return AlertGroup.create(
        team=team,
        route=route,
        source=route.source,
        group_key=unique("group-key"),
        group_key_hash=unique("hash"),
        title="Test alert",
        message="test",
        severity="critical",
        status="firing",
        alert_count=1,
        firing_count=1,
        common_labels={},
        label_values={},
        payload_summary={},
    )


def test_acknowledge_records_one_timeline_and_audit_for_any_source(db, monkeypatch):
    from app.services.alerts import actions
    group = _scope()
    monkeypatch.setattr(actions, "refresh_alert_group_correlations_safely", lambda *a, **k: None)
    monkeypatch.setattr(actions, "refresh_business_impacts_safely_for_group", lambda *a, **k: None)
    monkeypatch.setattr(actions, "refresh_business_services_safely_for_technical_service", lambda *a, **k: None)
    monkeypatch.setattr(actions, "update_alert_messages", lambda *a, **k: None)
    acknowledge_alert(group.id, source="slack")
    acknowledge_alert(group.id, source="telegram")
    audit = list(AuditLog.select().where(AuditLog.object_type == "alert_group", AuditLog.object_id == group.id, AuditLog.action == "alert_group.ack"))
    timeline = list(AlertEvent.select().where(AlertEvent.group == group.id, AlertEvent.event_type == "acknowledged"))
    assert len(audit) == 1
    assert len(timeline) == 1
    assert audit[0].data["source"] == "slack"


def test_resolve_records_one_timeline_and_audit_for_any_source(db, monkeypatch):
    from app.services.alerts import actions
    group = _scope()
    monkeypatch.setattr(actions, "refresh_alert_group_correlations_safely", lambda *a, **k: None)
    monkeypatch.setattr(actions, "refresh_business_impacts_safely_for_group", lambda *a, **k: None)
    monkeypatch.setattr(actions, "refresh_business_services_safely_for_technical_service", lambda *a, **k: None)
    monkeypatch.setattr(actions, "update_alert_messages", lambda *a, **k: None)
    resolve_alert(group.id, source="mattermost", api_token_id=None)
    resolve_alert(group.id, source="api", api_token_id=None)
    audit = list(AuditLog.select().where(AuditLog.object_type == "alert_group", AuditLog.object_id == group.id, AuditLog.action == "alert_group.resolve"))
    timeline = list(AlertEvent.select().where(AlertEvent.group == group.id, AlertEvent.event_type == "resolved"))
    assert len(audit) == 1
    assert len(timeline) == 1
    assert audit[0].data["source"] == "mattermost"
