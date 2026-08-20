from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import Alert, AlertComment, AlertEvent, AlertGroup
from app.services.alerts.retention import cleanup_alert_history


def _group(*, status="resolved", resolved_at=None, suffix="1"):
    return AlertGroup.create(
        source="test",
        group_key_hash=f"hash-{suffix}",
        group_key=f"group-{suffix}",
        title=f"Group {suffix}",
        status=status,
        resolved_at=resolved_at,
    )


def _alert(*, group=None, status="resolved", resolved_at=None, suffix="1"):
    return Alert.create(
        source="test",
        dedup_key=f"dedup-{suffix}",
        group_key=f"group-{suffix}",
        title=f"Alert {suffix}",
        status=status,
        resolved_at=resolved_at,
        group=group,
        payload={"large": "payload"},
        labels={"instance": suffix},
    )


def test_cleanup_is_disabled_when_retention_is_zero(db):
    now = utc_now()
    group = _group(resolved_at=now - timedelta(days=365))
    alert = _alert(group=group, resolved_at=group.resolved_at)

    result = cleanup_alert_history(retention_days=0, now=now)

    assert result["enabled"] is False
    assert result["groups_deleted"] == 0
    assert result["alerts_deleted"] == 0
    assert AlertGroup.get_or_none(AlertGroup.id == group.id) is not None
    assert Alert.get_or_none(Alert.id == alert.id) is not None


def test_cleanup_deletes_old_resolved_group_and_dependent_history(db):
    now = utc_now()
    resolved_at = now - timedelta(days=31)
    group = _group(resolved_at=resolved_at)
    alert = _alert(group=group, resolved_at=resolved_at)
    event = AlertEvent.create(
        group=group,
        alert=alert,
        event_type="resolved",
        message="done",
        created_at=resolved_at,
    )
    comment = AlertComment.create(
        group=group,
        alert=alert,
        body="historical note",
        created_at=resolved_at,
        updated_at=resolved_at,
    )

    result = cleanup_alert_history(retention_days=30, now=now)

    assert result["enabled"] is True
    assert result["groups_deleted"] == 1
    assert result["alerts_deleted"] == 1
    assert AlertGroup.get_or_none(AlertGroup.id == group.id) is None
    assert Alert.get_or_none(Alert.id == alert.id) is None
    assert AlertEvent.get_or_none(AlertEvent.id == event.id) is None
    assert AlertComment.get_or_none(AlertComment.id == comment.id) is None


def test_cleanup_keeps_recent_resolved_and_active_groups(db):
    now = utc_now()
    recent = _group(resolved_at=now - timedelta(days=29), suffix="recent")
    recent_alert = _alert(
        group=recent,
        resolved_at=recent.resolved_at,
        suffix="recent",
    )
    active = _group(
        status="firing",
        resolved_at=now - timedelta(days=90),
        suffix="active",
    )
    active_alert = _alert(
        group=active,
        status="firing",
        resolved_at=None,
        suffix="active",
    )

    result = cleanup_alert_history(retention_days=30, now=now)

    assert result["groups_deleted"] == 0
    assert AlertGroup.get_or_none(AlertGroup.id == recent.id) is not None
    assert Alert.get_or_none(Alert.id == recent_alert.id) is not None
    assert AlertGroup.get_or_none(AlertGroup.id == active.id) is not None
    assert Alert.get_or_none(Alert.id == active_alert.id) is not None


def test_cleanup_keeps_inconsistent_resolved_group_with_non_terminal_alert(db):
    now = utc_now()
    resolved_at = now - timedelta(days=90)
    group = _group(resolved_at=resolved_at, suffix="mixed")
    resolved = _alert(group=group, resolved_at=resolved_at, suffix="mixed-resolved")
    firing = _alert(
        group=group,
        status="firing",
        resolved_at=None,
        suffix="mixed-firing",
    )

    result = cleanup_alert_history(retention_days=30, now=now)

    assert result["groups_deleted"] == 0
    assert AlertGroup.get_or_none(AlertGroup.id == group.id) is not None
    assert Alert.get_or_none(Alert.id == resolved.id) is not None
    assert Alert.get_or_none(Alert.id == firing.id) is not None


def test_cleanup_deletes_old_standalone_resolved_alerts_in_batches(db):
    now = utc_now()
    old = now - timedelta(days=60)
    alerts = [
        _alert(group=None, resolved_at=old, suffix=f"standalone-{index}")
        for index in range(3)
    ]

    result = cleanup_alert_history(
        retention_days=30,
        batch_size=1,
        now=now,
    )

    assert result["groups_deleted"] == 0
    assert result["standalone_alerts_deleted"] == 3
    assert result["alerts_deleted"] == 3
    assert result["batches"] == 3
    for alert in alerts:
        assert Alert.get_or_none(Alert.id == alert.id) is None


@pytest.mark.parametrize("retention_days", [-1, "-5"])
def test_cleanup_rejects_negative_retention(db, retention_days):
    with pytest.raises(ValueError, match="retention_days"):
        cleanup_alert_history(retention_days=retention_days)


@pytest.mark.parametrize("batch_size", [0, -1])
def test_cleanup_rejects_non_positive_batch_size(db, batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        cleanup_alert_history(retention_days=30, batch_size=batch_size)
