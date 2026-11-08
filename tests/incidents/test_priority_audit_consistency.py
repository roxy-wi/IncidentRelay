"""Canonical audit for manual AlertGroup priority changes."""
from contextlib import nullcontext
from types import SimpleNamespace

from app.services.incidents import priorities


def test_manual_priority_set_records_exactly_one_audit(monkeypatch):
    group = SimpleNamespace(
        id=21, team_id=8,
        team=SimpleNamespace(group_id=3),
        priority_slug="p3", priority_set_manually=False,
    )
    writes = []
    updates = []
    monkeypatch.setattr(priorities, "db", SimpleNamespace(atomic=lambda: nullcontext()))
    monkeypatch.setattr(priorities.alerts_repo, "get_alert_group", lambda _id: group)
    monkeypatch.setattr(priorities.incidents_repo, "get_priority_by_slug", lambda slug: SimpleNamespace(slug=slug))

    def fake_set(group_id, slug, *, user_id, manual):
        group.priority_slug = slug
        group.priority_set_manually = manual
        updates.append((group_id, slug, user_id))
        return group

    monkeypatch.setattr(priorities.incidents_repo, "set_incident_priority", fake_set)
    monkeypatch.setattr(priorities.audit_repo, "create_audit_log", lambda **kwargs: writes.append(kwargs))
    monkeypatch.setattr(priorities, "update_alert_messages", lambda *args, **kwargs: None)

    priorities.set_incident_priority(
        group_id=21, priority="p2", user_id=16, source="api",
    )
    priorities.set_incident_priority(
        group_id=21, priority="p2", user_id=16, source="api",
    )

    assert updates == [(21, "p2", 16)]
    assert len(writes) == 1
    assert writes[0]["action"] == "alert_group.priority.set"
    assert writes[0]["group_id"] == 3
    assert writes[0]["team_id"] == 8
    assert writes[0]["user_id"] == 16
    assert writes[0]["data"]["source"] == "api"


def test_reset_manual_priority_creates_distinct_audit(monkeypatch):
    group = SimpleNamespace(
        id=21, team_id=8, team=SimpleNamespace(group_id=3),
        severity="critical", priority_slug="p2", priority_set_manually=True,
    )
    priority = SimpleNamespace(id=1, slug="p1")
    audit = []
    monkeypatch.setattr(priorities, "db", SimpleNamespace(atomic=lambda: nullcontext()))
    monkeypatch.setattr(priorities.alerts_repo, "get_alert_group", lambda _id: group)
    monkeypatch.setattr(priorities, "resolve_automatic_incident_priority", lambda _group: (priority, "recalculate"))

    def fake_reset(_group_id, _priority, *, update_mode):
        group.priority_slug = priority.slug
        group.priority_set_manually = False
        return group

    monkeypatch.setattr(priorities.incidents_repo, "reset_incident_priority", fake_reset)
    monkeypatch.setattr(priorities.audit_repo, "create_audit_log", lambda **kwargs: audit.append(kwargs))
    monkeypatch.setattr(priorities, "update_alert_messages", lambda *args, **kwargs: None)

    priorities.reset_incident_priority(group_id=21, user_id=16, source="api")
    priorities.reset_incident_priority(group_id=21, user_id=16, source="api")

    assert len(audit) == 1
    assert audit[0]["action"] == "alert_group.priority.reset"
    assert audit[0]["data"]["manual"] is False
    assert audit[0]["user_id"] == 16
