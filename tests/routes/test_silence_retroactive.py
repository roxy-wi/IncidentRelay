from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db import silences_repo
from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
    AuditLog,
    SilenceAlertApplication,
)
from app.services.alerts.actions import acknowledge_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.silences import (
    process_silence_lifecycle,
    reconcile_silence,
)
from tests.factories import (
    create_escalation_policy,
    create_escalation_policy_rule,
    create_group,
    create_route,
    create_silence,
    create_team,
    unique,
)


def _alert_payload(team_slug: str, *, dedup_key: str | None = None) -> dict:
    return {
        "source": "alertmanager",
        "team_slug": team_slug,
        "external_id": unique("external"),
        "dedup_key": dedup_key or unique("dedup"),
        "title": "DiskFull",
        "message": "/var is 95% full",
        "severity": "critical",
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host1",
        },
        "payload": {},
        "status": "firing",
    }


def _fixture():
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team)
    return group, team, route


def test_default_silence_does_not_change_existing_firing_alert(db):
    _, team, _ = _fixture()
    result = upsert_alert(_alert_payload(team.slug))

    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=False,
    )
    reconcile_silence(silence)

    alert = Alert.get_by_id(result.alert.id)
    group = AlertGroup.get_by_id(result.group.id)

    assert alert.status == "firing"
    assert group.status == "firing"
    assert SilenceAlertApplication.select().count() == 0


def test_opted_in_silence_changes_existing_firing_alert(db):
    _, team, _ = _fixture()
    result = upsert_alert(_alert_payload(team.slug))

    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=True,
    )
    applied = reconcile_silence(silence)

    alert = Alert.get_by_id(result.alert.id)
    group = AlertGroup.get_by_id(result.group.id)
    application = SilenceAlertApplication.get()

    assert applied["silenced"] == 1
    assert alert.status == "silenced"
    assert alert.silenced is True
    assert group.status == "silenced"
    assert group.notification_pending is False
    assert group.next_escalation_at is None
    assert application.silence_id == silence.id
    assert application.alert_id == alert.id
    assert application.previous_status == "firing"
    assert application.source == "retroactive"
    assert application.active is True
    assert AlertEvent.select().where(
        (AlertEvent.alert == alert.id)
        & (AlertEvent.event_type == "silenced")
    ).exists()
    assert AuditLog.select().where(
        (AuditLog.object_type == "alert")
        & (AuditLog.object_id == alert.id)
        & (AuditLog.action == "silence.alert_applied")
    ).exists()


def test_alert_created_during_silence_reactivates_after_expiry(db):
    _, team, _ = _fixture()
    now = utc_now()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1),
    )

    result = upsert_alert(_alert_payload(team.slug))
    alert = Alert.get_by_id(result.alert.id)
    group = AlertGroup.get_by_id(result.group.id)

    assert alert.status == "silenced"
    assert group.status == "silenced"
    assert SilenceAlertApplication.get().source == "new_alert"

    processed = process_silence_lifecycle(now=silence.ends_at)

    alert = Alert.get_by_id(alert.id)
    group = AlertGroup.get_by_id(group.id)
    application = SilenceAlertApplication.get()

    assert processed["alerts_reactivated"] == 1
    assert alert.status == "firing"
    assert alert.silenced is False
    assert group.status == "firing"
    assert group.notification_pending is True
    assert application.active is False
    assert application.release_reason == "expired"


def test_silence_can_keep_alert_silenced_after_expiry(db):
    _, team, _ = _fixture()
    now = utc_now()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1),
        reactivate_on_end=False,
    )
    result = upsert_alert(_alert_payload(team.slug))

    processed = process_silence_lifecycle(now=silence.ends_at)

    alert = Alert.get_by_id(result.alert.id)
    group = AlertGroup.get_by_id(result.group.id)
    application = SilenceAlertApplication.get()

    assert processed["alerts_reactivated"] == 0
    assert alert.status == "silenced"
    assert alert.silenced is True
    assert group.status == "silenced"
    assert application.active is True
    assert application.released_at is None


def test_disabling_silence_can_retain_affected_alerts(db):
    _, team, _ = _fixture()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        reactivate_on_end=False,
    )
    result = upsert_alert(_alert_payload(team.slug))

    silence = silences_repo.disable_silence(silence.id)
    released = reconcile_silence(silence)

    assert released["retained"] == 1
    assert released["reactivated"] == 0
    assert Alert.get_by_id(result.alert.id).status == "silenced"
    assert SilenceAlertApplication.get().active is True
    assert AuditLog.select().where(
        (AuditLog.object_type == "silence")
        & (AuditLog.object_id == silence.id)
        & (AuditLog.action == "silence.alerts_retained")
    ).exists()


def test_enabling_reactivation_releases_retained_alerts(db):
    _, team, _ = _fixture()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        reactivate_on_end=False,
    )
    result = upsert_alert(_alert_payload(team.slug))

    silence = silences_repo.disable_silence(silence.id)
    reconcile_silence(silence)
    silence = silences_repo.update_silence(
        silence.id,
        {"reactivate_on_end": True},
    )
    released = reconcile_silence(silence)

    assert released["reactivated"] == 1
    assert Alert.get_by_id(result.alert.id).status == "firing"
    assert AlertGroup.get_by_id(result.group.id).status == "firing"
    assert SilenceAlertApplication.get().active is False


def test_overlapping_silences_keep_alert_silenced_until_last_release(db):
    _, team, _ = _fixture()
    first = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
    )
    second = create_silence(
        team,
        matchers={"labels": {"severity": "critical"}},
    )
    result = upsert_alert(_alert_payload(team.slug))

    assert SilenceAlertApplication.select().where(
        SilenceAlertApplication.active == True
    ).count() == 2

    first = silences_repo.disable_silence(first.id)
    reconcile_silence(first)

    assert Alert.get_by_id(result.alert.id).status == "silenced"
    assert AlertGroup.get_by_id(result.group.id).status == "silenced"

    second = silences_repo.disable_silence(second.id)
    reconcile_silence(second)

    assert Alert.get_by_id(result.alert.id).status == "firing"
    assert AlertGroup.get_by_id(result.group.id).status == "firing"


def test_scheduled_retroactive_silence_is_applied_by_scheduler(db):
    _, team, _ = _fixture()
    result = upsert_alert(_alert_payload(team.slug))
    now = utc_now()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        starts_at=now + timedelta(minutes=5),
        ends_at=now + timedelta(minutes=10),
        apply_to_existing=True,
    )

    reconcile_silence(silence, now=now)
    silence = silence.__class__.get_by_id(silence.id)

    assert silence.reconciled_at is None
    assert Alert.get_by_id(result.alert.id).status == "firing"

    processed = process_silence_lifecycle(now=silence.starts_at)

    assert processed["alerts_silenced"] == 1
    assert Alert.get_by_id(result.alert.id).status == "silenced"
    assert AlertGroup.get_by_id(result.group.id).status == "silenced"


def test_retroactive_silence_does_not_remove_acknowledgement(db):
    _, team, _ = _fixture()
    result = upsert_alert(_alert_payload(team.slug))
    acknowledge_alert(result.group.id)

    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=True,
    )
    reconcile_silence(silence)

    group = AlertGroup.get_by_id(result.group.id)
    alert = Alert.get_by_id(result.alert.id)

    assert group.status == "acknowledged"
    assert alert.status == "firing"
    assert SilenceAlertApplication.select().count() == 0


def test_repeated_scheduler_execution_is_idempotent(db):
    _, team, _ = _fixture()
    now = utc_now()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1),
    )
    result = upsert_alert(_alert_payload(team.slug))

    first = process_silence_lifecycle(now=silence.ends_at)
    second = process_silence_lifecycle(now=silence.ends_at + timedelta(seconds=1))

    assert first["alerts_reactivated"] == 1
    assert second["alerts_reactivated"] == 0
    assert Alert.get_by_id(result.alert.id).status == "firing"
    assert SilenceAlertApplication.select().count() == 1


def test_silence_api_exposes_apply_to_existing(client, admin_headers, db):
    _, team, _ = _fixture()
    now = utc_now()

    response = client.post(
        "/api/silences",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "name": "Retroactive",
            "reason": "Alert storm",
            "starts_at": (now - timedelta(minutes=1)).isoformat() + "Z",
            "ends_at": (now + timedelta(minutes=10)).isoformat() + "Z",
            "matchers": {"labels": {"alertname": "DiskFull"}},
            "apply_to_existing": True,
            "reactivate_on_end": False,
        },
    )

    assert response.status_code == 201, response.get_json()
    assert response.get_json()["apply_to_existing"] is True
    assert response.get_json()["reactivate_on_end"] is False


def test_legacy_silenced_alert_without_application_is_reactivated(db):
    _, team, _ = _fixture()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
    )
    result = upsert_alert(_alert_payload(team.slug))
    SilenceAlertApplication.delete().execute()

    silence = silences_repo.disable_silence(silence.id)
    processed = process_silence_lifecycle(now=utc_now())

    assert processed["alerts_reactivated"] == 1
    assert Alert.get_by_id(result.alert.id).status == "firing"
    assert AlertGroup.get_by_id(result.group.id).notification_pending is True


def test_enable_endpoint_reconciles_retroactive_silence(
    client,
    admin_headers,
    db,
):
    _, team, _ = _fixture()
    result = upsert_alert(_alert_payload(team.slug))
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=True,
    )
    silence.enabled = False
    silence.save()

    response = client.post(
        f"/api/silences/{silence.id}/enable",
        headers=admin_headers,
        json={},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["enabled"] is True
    assert Alert.get_by_id(result.alert.id).status == "silenced"


def test_silence_ui_exposes_retroactive_option():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    template = (root / "app/templates/pages/silences.html").read_text(
        encoding="utf-8"
    )
    source = (root / "app/static/js/pages/silences.js").read_text(
        encoding="utf-8"
    )

    assert 'id="silence-apply-to-existing"' in template
    assert 'id="silence-reactivate-on-end"' in template
    assert "apply_to_existing:" in source
    assert "reactivate_on_end:" in source
    assert '.prop("checked", Boolean(silence.apply_to_existing))' in source
    assert '$("#silence-reactivate-on-end").prop("checked", true)' in source


def test_later_retroactive_silence_attaches_to_already_silenced_alert(db):
    _, team, _ = _fixture()
    first = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
    )
    result = upsert_alert(_alert_payload(team.slug))

    second = create_silence(
        team,
        matchers={"labels": {"severity": "critical"}},
        apply_to_existing=True,
    )
    reconcile_silence(second)

    assert SilenceAlertApplication.select().where(
        SilenceAlertApplication.active == True
    ).count() == 2

    first = silences_repo.disable_silence(first.id)
    reconcile_silence(first)

    assert Alert.get_by_id(result.alert.id).status == "silenced"
    assert AlertGroup.get_by_id(result.group.id).status == "silenced"


def test_acknowledged_group_stays_acknowledged_when_silence_ends(db):
    _, team, _ = _fixture()
    now = utc_now()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1),
    )
    result = upsert_alert(_alert_payload(team.slug))
    acknowledge_alert(result.group.id)

    process_silence_lifecycle(now=silence.ends_at)

    group = AlertGroup.get_by_id(result.group.id)
    alert = Alert.get_by_id(result.alert.id)

    assert group.status == "acknowledged"
    assert alert.status == "firing"
    assert group.notification_pending is False


def test_reactivated_notified_group_schedules_immediate_update(db):
    _, team, _ = _fixture()
    result = upsert_alert(_alert_payload(team.slug))
    notified_at = utc_now() - timedelta(minutes=1)
    group = AlertGroup.get_by_id(result.group.id)
    group.last_notification_at = notified_at
    group.save()

    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=True,
    )
    reconcile_silence(silence)

    release_at = utc_now() + timedelta(seconds=5)
    silence = silences_repo.disable_silence(silence.id)
    reconcile_silence(silence, now=release_at)

    group = AlertGroup.get_by_id(group.id)
    assert group.status == "firing"
    assert group.notification_pending is True
    assert group.notification_due_at == release_at
    assert group.notification_reason == "reactivated"


def test_reactivation_resets_escalation_from_release_time(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    policy = create_escalation_policy(team)
    create_escalation_policy_rule(
        policy,
        delay_seconds=120,
        target_type="user",
    )
    create_route(team, escalation_policy=policy)

    now = utc_now()
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1),
    )
    result = upsert_alert(_alert_payload(team.slug))

    process_silence_lifecycle(now=silence.ends_at)

    alert_group = AlertGroup.get_by_id(result.group.id)
    assert alert_group.status == "firing"
    assert alert_group.escalation_level == 0
    assert alert_group.next_escalation_at == silence.ends_at + timedelta(seconds=120)
