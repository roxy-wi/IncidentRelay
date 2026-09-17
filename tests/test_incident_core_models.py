import pytest

from app.modules.db.models import Alert, AlertGroup, Incident, IncidentAlertGroupLink
from tests.factories import create_group, create_team, create_user, unique


@pytest.fixture(autouse=True)
def cleanup_incident_core(db):
    """Keep first-class Incident rows isolated until global cleanup owns them."""
    IncidentAlertGroupLink.delete().execute()
    Incident.delete().execute()
    yield
    IncidentAlertGroupLink.delete().execute()
    Incident.delete().execute()


def _create_alert_group(team, *, assignee=None):
    key = unique("incident-core-group")
    return AlertGroup.create(
        team=team,
        assignee=assignee,
        source="manual",
        group_key_hash=key,
        group_key=key,
        title=unique("Alert group"),
    )


def test_first_class_incident_can_exist_without_technical_records(db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)

    alert_group_count = AlertGroup.select().count()
    alert_count = Alert.select().count()

    incident = Incident.create(
        team=team,
        title="Database latency investigation",
        assignee=user,
        declared_by=user,
    )

    assert incident.workflow_status == "declared"
    assert incident.row_version == 1
    assert AlertGroup.select().count() == alert_group_count
    assert Alert.select().count() == alert_count
    assert IncidentAlertGroupLink.select().count() == 0


def test_incident_can_link_multiple_alert_groups_without_mutating_them(db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    first_group = _create_alert_group(team)
    second_group = _create_alert_group(team)

    incident = Incident.create(
        team=team,
        title="Shared upstream outage",
        declared_by=user,
    )
    IncidentAlertGroupLink.create(
        incident=incident, alert_group=first_group, linked_by=user
    )
    IncidentAlertGroupLink.create(
        incident=incident, alert_group=second_group, linked_by=user
    )

    assert incident.alert_group_links.count() == 2
    assert AlertGroup.get_by_id(first_group.id).status == "firing"
    assert AlertGroup.get_by_id(second_group.id).status == "firing"


def test_incident_and_alert_group_assignments_are_independent(db):
    group = create_group()
    team = create_team(group)
    technical_owner = create_user(group=group)
    incident_owner = create_user(group=group)
    replacement_owner = create_user(group=group)

    alert_group = _create_alert_group(team, assignee=technical_owner)
    incident = Incident.create(
        team=team,
        title="Operational investigation",
        assignee=incident_owner,
        declared_by=incident_owner,
    )
    IncidentAlertGroupLink.create(
        incident=incident, alert_group=alert_group, linked_by=incident_owner
    )

    incident.assignee = replacement_owner
    incident.save(only=[Incident.assignee])

    assert AlertGroup.get_by_id(alert_group.id).assignee_id == technical_owner.id
    assert Incident.get_by_id(incident.id).assignee_id == replacement_owner.id
