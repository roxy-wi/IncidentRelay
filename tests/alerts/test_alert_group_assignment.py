from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import AlertEvent, AlertGroup, AuditLog
from app.services.alerts.assignment import (
    AlertGroupAssignmentError,
    set_alert_group_assignee,
)
from tests.factories import add_user_to_team, create_group, create_team, create_user


def _group(team, *, assignee=None):
    now = utc_now()
    return AlertGroup.create(
        team=team,
        assignee=assignee,
        source="manual",
        group_key_hash="assignment-test",
        group_key="assignment-test",
        title="Assignment test",
        status="acknowledged",
        acknowledged_by=assignee,
        acknowledged_at=now,
        escalation_level=2,
        escalation_repeat_count=3,
        next_escalation_at=now + timedelta(minutes=10),
        last_escalated_at=now - timedelta(minutes=5),
    )


def test_manual_assignment_changes_only_technical_assignee(db):
    access_group = create_group()
    team = create_team(access_group)
    actor = create_user(group=access_group)
    previous = create_user(group=access_group)
    replacement = create_user(group=access_group)
    add_user_to_team(team, actor, role="responder")
    add_user_to_team(team, previous, role="responder")
    add_user_to_team(team, replacement, role="responder")

    alert_group = _group(team, assignee=previous)
    before = {
        "status": alert_group.status,
        "acknowledged_by_id": alert_group.acknowledged_by_id,
        "acknowledged_at": alert_group.acknowledged_at,
        "escalation_level": alert_group.escalation_level,
        "escalation_repeat_count": alert_group.escalation_repeat_count,
        "next_escalation_at": alert_group.next_escalation_at,
        "last_escalated_at": alert_group.last_escalated_at,
    }

    updated = set_alert_group_assignee(
        alert_group,
        replacement.id,
        actor_user_id=actor.id,
    )

    assert updated.assignee_id == replacement.id
    assert updated.status == before["status"]
    assert updated.acknowledged_by_id == before["acknowledged_by_id"]
    assert updated.acknowledged_at == before["acknowledged_at"]
    assert updated.escalation_level == before["escalation_level"]
    assert updated.escalation_repeat_count == before["escalation_repeat_count"]
    assert updated.next_escalation_at == before["next_escalation_at"]
    assert updated.last_escalated_at == before["last_escalated_at"]

    event = (
        AlertEvent.select()
        .where(AlertEvent.group == alert_group.id)
        .order_by(AlertEvent.id.desc())
        .get()
    )
    assert event.event_type == "assignee_changed"
    assert event.user_id == actor.id

    audit = (
        AuditLog.select()
        .where(
            AuditLog.object_type == "alert_group",
            AuditLog.object_id == alert_group.id,
        )
        .order_by(AuditLog.id.desc())
        .get()
    )
    assert audit.action == "alert_group_assignee_changed"
    assert audit.team_id == team.id


def test_manual_assignment_rejects_user_outside_team(db):
    access_group = create_group()
    team = create_team(access_group)
    outsider = create_user(group=access_group)
    alert_group = _group(team)

    with pytest.raises(
        AlertGroupAssignmentError,
        match="active member of the AlertGroup team",
    ):
        set_alert_group_assignee(alert_group, outsider.id)


def test_manual_assignment_can_unassign_without_touching_lifecycle(db):
    access_group = create_group()
    team = create_team(access_group)
    assignee = create_user(group=access_group)
    add_user_to_team(team, assignee, role="responder")
    alert_group = _group(team, assignee=assignee)
    next_escalation_at = alert_group.next_escalation_at

    updated = set_alert_group_assignee(alert_group, None)

    assert updated.assignee_id is None
    assert updated.status == "acknowledged"
    assert updated.escalation_level == 2
    assert updated.escalation_repeat_count == 3
    assert updated.next_escalation_at == next_escalation_at
