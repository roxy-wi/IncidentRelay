import pytest

from app.modules.db.models import AlertGroup, AuditLog, Incident, IncidentAlertGroupLink, IncidentEvent
from app.services.incidents import core
from tests.factories import add_user_to_team, create_group, create_service, create_team, create_user, unique


@pytest.fixture(autouse=True)
def cleanup_incident_core(db):
    IncidentAlertGroupLink.delete().execute()
    IncidentEvent.delete().execute()
    Incident.delete().execute()
    yield
    IncidentAlertGroupLink.delete().execute()
    IncidentEvent.delete().execute()
    Incident.delete().execute()


def _alert_group(team, *, assignee=None):
    key = unique("incident-core-group")
    return AlertGroup.create(team=team, assignee=assignee, source="manual", group_key_hash=key, group_key=key, title=key)


def test_create_incident_is_operational_only(db):
    group = create_group()
    team = create_team(group)
    actor = create_user(group=group)
    add_user_to_team(team, actor)
    incident = core.create_incident(team_id=team.id, title="Operational incident", user_id=actor.id, assignee_id=actor.id)
    assert incident.workflow_status == "declared"
    assert AlertGroup.select().count() == 0
    assert IncidentEvent.get(IncidentEvent.incident == incident.id).event_type == "incident_declared"
    assert AuditLog.get(AuditLog.object_type == "incident", AuditLog.object_id == incident.id).action == "incident_declared"


def test_transition_uses_optimistic_concurrency(db):
    group = create_group(); team = create_team(group); actor = create_user(group=group); add_user_to_team(team, actor)
    incident = core.create_incident(team_id=team.id, title="Race", user_id=actor.id)
    updated = core.transition_incident(incident.id, "investigating", expected_version=1, user_id=actor.id)
    assert updated.row_version == 2
    with pytest.raises(core.IncidentConflictError):
        core.transition_incident(incident.id, "resolved", expected_version=1, user_id=actor.id)


def test_invalid_transition_is_rejected(db):
    group = create_group(); team = create_team(group); actor = create_user(group=group); add_user_to_team(team, actor)
    incident = core.create_incident(team_id=team.id, title="Invalid transition", user_id=actor.id)
    with pytest.raises(core.IncidentValidationError, match="cannot change incident status"):
        core.transition_incident(incident.id, "closed", expected_version=1, user_id=actor.id)


def test_link_unlink_relink_preserves_history(db):
    group = create_group(); team = create_team(group); actor = create_user(group=group); add_user_to_team(team, actor)
    alert_group = _alert_group(team)
    incident = core.create_incident(team_id=team.id, title="Link history", user_id=actor.id)
    first = core.link_alert_group(incident.id, alert_group.id, relation_type="primary", user_id=actor.id)
    core.unlink_alert_group(incident.id, alert_group.id, user_id=actor.id)
    second = core.link_alert_group(incident.id, alert_group.id, relation_type="related", user_id=actor.id)
    assert first.id != second.id
    assert IncidentAlertGroupLink.select().where(IncidentAlertGroupLink.incident == incident.id).count() == 2
    assert IncidentAlertGroupLink.get_by_id(first.id).removed_at is not None
    assert IncidentAlertGroupLink.get_by_id(second.id).removed_at is None


def test_alert_group_cannot_link_to_two_open_incidents(db):
    group = create_group(); team = create_team(group); actor = create_user(group=group); add_user_to_team(team, actor)
    alert_group = _alert_group(team)
    first = core.create_incident(team_id=team.id, title="First", user_id=actor.id)
    second = core.create_incident(team_id=team.id, title="Second", user_id=actor.id)
    core.link_alert_group(first.id, alert_group.id, user_id=actor.id)
    with pytest.raises(core.IncidentConflictError, match="already linked"):
        core.link_alert_group(second.id, alert_group.id, user_id=actor.id)


def test_incident_assignment_does_not_change_alert_group_assignment(db):
    group = create_group(); team = create_team(group)
    technical = create_user(group=group); operational = create_user(group=group); replacement = create_user(group=group)
    for user in (technical, operational, replacement): add_user_to_team(team, user)
    alert_group = _alert_group(team, assignee=technical)
    incident = core.create_incident(team_id=team.id, title="Independent ownership", user_id=operational.id, assignee_id=operational.id)
    core.link_alert_group(incident.id, alert_group.id, user_id=operational.id)
    updated = core.assign_incident(incident.id, assignee_id=replacement.id, expected_version=incident.row_version, user_id=operational.id)
    assert updated.assignee_id == replacement.id
    assert AlertGroup.get_by_id(alert_group.id).assignee_id == technical.id
