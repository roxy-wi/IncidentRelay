"""Episodes and discovery requests share each technical lifecycle transaction."""

from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db import (
    alert_episodes_repo,
    alerts_repo,
    changes_repo,
    heartbeats_repo,
    soft_delete_hardening,
)
from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
    AlertGroupEpisode,
    AuditLog,
    ChangeJob,
    Heartbeat,
    Incident,
    IncidentAlertGroupLink,
)
from app.services.alerts import actions, lifecycle
from app.services.alerts.lifecycle import upsert_alert
from app.services.alerts.shelving import shelve_alert_group, unshelve_alert_group
from app.services.heartbeats import service as heartbeat_service
from app.services.incidents.manual import create_manual_alert_group
from app.services.orchestration.runtime import RuntimeResult
from tests.factories import (
    create_group,
    create_heartbeat,
    create_route,
    create_service,
    create_silence,
    create_team,
    unique,
)


@pytest.fixture
def intake(db, monkeypatch):
    team = create_team(create_group())
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": unique("event"),
        "dedup_key": unique("key"),
        "title": "Disk full",
        "severity": "critical",
        "status": "firing",
        "labels": {"alertname": "DiskFull"},
        "payload": {},
    }
    return team, route, data


def _episodes(group_id):
    return list(
        AlertGroupEpisode.select()
        .where(AlertGroupEpisode.alert_group == group_id)
        .order_by(AlertGroupEpisode.ordinal)
    )


def _job(episode):
    return ChangeJob.get(
        ChangeJob.job_type == "discover_episode",
        ChangeJob.entity_id == episode.id,
    )


def _remove_episode_tracking(group):
    """Represent a persisted group created before episode recording existed."""
    episodes = AlertGroupEpisode.select(AlertGroupEpisode.id).where(
        AlertGroupEpisode.alert_group == group.id
    )
    AlertGroup.update(current_episode=None).where(AlertGroup.id == group.id).execute()
    ChangeJob.delete().where(
        ChangeJob.job_type == "discover_episode", ChangeJob.entity_id.in_(episodes)
    ).execute()
    AlertGroupEpisode.delete().where(
        AlertGroupEpisode.alert_group == group.id
    ).execute()
    return AlertGroup.get_by_id(group.id)


def _snapshot():
    return [
        list(model.select().order_by(model.id).dicts())
        for model in (
            AlertGroup,
            Alert,
            AlertGroupEpisode,
            ChangeJob,
            AlertEvent,
            AuditLog,
        )
    ]


def _fail(*args, **kwargs):
    raise RuntimeError("injected lifecycle failure")


def _inject(monkeypatch, fault):
    target, field = {
        "episode": (AlertGroupEpisode, "create"),
        "job": (changes_repo, "request_job"),
        "child": (alerts_repo, "create_alert"),
        "event": (alerts_repo, "create_alert_event"),
    }[fault]
    monkeypatch.setattr(target, field, _fail)


def test_intake_recovery_and_reopen_have_distinct_cycles(intake):
    _, _, data = intake
    first = upsert_alert(dict(data))
    episode = _episodes(first.group.id)[0]
    assert first.group.current_episode_id == episode.id
    assert episode.start_quality == "exact"
    assert episode.started_at == first.alert.first_seen_at
    assert episode.start_event.event_type == "created"
    assert _job(episode).requested_generation == 1

    upsert_alert(dict(data))
    assert len(_episodes(first.group.id)) == 1
    assert _job(episode).requested_generation == 1

    recovered = upsert_alert(dict(data, status="resolved"))
    closed = AlertGroupEpisode.get_by_id(episode.id)
    assert closed.state == "resolved" and closed.ended_at == recovered.group.resolved_at
    assert closed.end_event.alert_id == first.alert.id
    assert recovered.group.current_episode_id is None
    assert _job(episode).requested_generation == 2

    reopened = upsert_alert(dict(data))
    cycles = _episodes(first.group.id)
    assert [row.ordinal for row in cycles] == [1, 2]
    assert [row.state for row in cycles] == ["resolved", "open"]
    assert reopened.group.current_episode_id == cycles[1].id
    assert cycles[1].started_at == reopened.alert.first_seen_at
    assert cycles[1].start_event.alert_id == reopened.alert.id
    assert _job(cycles[1]).requested_generation == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_ack_shelve_unshelve_and_ack_to_firing_keep_episode(intake, legacy):
    _, _, data = intake
    first = upsert_alert(dict(data))
    group = _remove_episode_tracking(first.group) if legacy else first.group
    episode_id = group.current_episode_id
    actions.acknowledge_alert(first.group.id)
    shelve_alert_group(first.group.id, duration_seconds=60)
    unshelve_alert_group(first.group.id)
    added = upsert_alert(dict(data, dedup_key=unique("second")))
    assert added.group.status == "firing"
    assert added.group.current_episode_id == episode_id
    assert len(_episodes(first.group.id)) == (0 if legacy else 1)
    if legacy:
        assert not ChangeJob.select().exists()
    else:
        assert _job(AlertGroupEpisode.get_by_id(episode_id)).requested_generation == 1


def test_manual_creation_and_callback_resolution_share_episode_contract(intake):
    team, _, _ = intake
    group = create_manual_alert_group(
        {"team_id": team.id, "title": "Manual", "notify": False}
    )
    episode = _episodes(group.id)[0]
    assert episode.start_event.event_type == "manual_created"
    resolved = actions.resolve_alert(group.id, source="telegram")
    actions.resolve_alert(group.id, source="telegram")
    saved = AlertGroupEpisode.get_by_id(episode.id)
    assert saved.state == "resolved" and saved.ended_at == resolved.resolved_at
    assert saved.end_event.event_type == "resolved"
    assert _job(saved).requested_generation == 2
    assert AlertGroup.get_by_id(group.id).current_episode_id is None


def test_terminal_input_does_not_invent_an_episode(intake):
    team, _, data = intake
    assert upsert_alert(dict(data, status="resolved")).group is None
    group = alerts_repo.create_alert_group(
        team=team,
        source="test",
        title="Terminal",
        group_key=unique("terminal"),
        status="resolved",
        resolved_at=utc_now(),
    )
    assert group.current_episode_id is None
    assert not AlertGroupEpisode.select().exists()
    assert not ChangeJob.select().exists()


@pytest.mark.parametrize("resolution", ["recovery", "manual", "resource"])
def test_legacy_group_is_tracked_only_after_a_genuine_reopen(intake, resolution):
    data = intake[2]
    initial = upsert_alert(dict(data))
    legacy = _remove_episode_tracking(initial.group)
    repeated = upsert_alert(dict(data))
    other_data = dict(data, dedup_key=unique("second"))
    added = upsert_alert(dict(other_data))
    recalculated = alerts_repo.recalculate_alert_group(legacy)
    assert repeated.group.id == added.group.id == recalculated.id == legacy.id
    assert recalculated.current_episode_id is None
    assert not AlertGroupEpisode.select().exists()
    assert not ChangeJob.select().exists()

    if resolution == "recovery":
        upsert_alert(dict(data, status="resolved"))
        upsert_alert(dict(other_data, status="resolved"))
    elif resolution == "manual":
        actions.resolve_alert(legacy.id)
    else:
        soft_delete_hardening.resolve_alert_groups_by_ids([legacy.id])
    assert AlertGroup.get_by_id(legacy.id).status == "resolved"
    assert not AlertGroupEpisode.select().exists()
    assert not ChangeJob.select().exists()

    reopened = upsert_alert(dict(data))
    episode = AlertGroupEpisode.get()
    assert reopened.group.id == legacy.id
    assert reopened.alert.id != initial.alert.id
    assert reopened.group.current_episode_id == episode.id
    assert episode.ordinal == 1 and episode.start_quality == "exact"
    assert episode.started_at == reopened.alert.first_seen_at
    assert episode.started_at > legacy.first_seen_at
    assert episode.start_event.event_type == "reopened"
    assert _job(episode).requested_generation == 1


def test_missing_start_never_initializes_a_legacy_episode(intake):
    from app.modules.db import incident_core_repo

    group = _remove_episode_tracking(upsert_alert(dict(intake[2])).group)
    event = AlertEvent.create(group=group, event_type="updated")
    with incident_core_repo.write_transaction():
        locked = incident_core_repo.lock_alert_group(group.id)
        assert alert_episodes_repo.open_episode(locked, event=event) is None
    assert AlertGroup.get_by_id(group.id).current_episode_id is None
    assert not AlertGroupEpisode.select().exists()
    assert not ChangeJob.select().exists()


@pytest.mark.parametrize("resolved_target", [False, True])
def test_merge_tracks_legacy_target_only_when_it_reopens(intake, resolved_target):
    team, _, data = intake
    target = _remove_episode_tracking(upsert_alert(dict(data)).group)
    if resolved_target:
        actions.resolve_alert(target.id)
    source = create_manual_alert_group(
        {"team_id": team.id, "title": "Source", "notify": False}
    )

    merged = alerts_repo.merge_alert_groups(target.id, [source.id])

    assert merged.status == "firing"
    assert len(_episodes(target.id)) == int(resolved_target)
    assert ChangeJob.select().count() == 1 + int(resolved_target)
    assert source.current_episode_id != merged.current_episode_id
    if resolved_target:
        episode = merged.current_episode
        assert episode.ordinal == 1 and episode.start_quality == "exact"
        assert _job(episode).requested_generation == 1
    else:
        assert merged.current_episode_id is None


@pytest.mark.parametrize("fault", ["episode", "job", "child", "event"])
def test_failed_creation_leaves_no_group_child_episode_or_job(
    intake, monkeypatch, fault
):
    data = intake[2]
    before = _snapshot()
    with monkeypatch.context() as patch:
        _inject(patch, fault)
        with pytest.raises(RuntimeError, match="injected"):
            upsert_alert(dict(data))
    assert _snapshot() == before
    assert upsert_alert(dict(data)).group.current_episode_id is not None


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("fault", ["episode", "job", "child", "event"])
def test_failed_reopen_keeps_previous_cycle_and_can_retry(
    intake, monkeypatch, fault, legacy
):
    data = intake[2]
    first = upsert_alert(dict(data))
    if legacy:
        _remove_episode_tracking(first.group)
    upsert_alert(dict(data, status="resolved"))
    before = _snapshot()
    with monkeypatch.context() as patch:
        _inject(patch, fault)
        with pytest.raises(RuntimeError, match="injected"):
            upsert_alert(dict(data))
    assert _snapshot() == before
    assert upsert_alert(dict(data)).group.id == first.group.id
    assert len(_episodes(first.group.id)) == (1 if legacy else 2)


@pytest.mark.parametrize("operation", ["recovery", "manual"])
@pytest.mark.parametrize("fault", ["job", "event"])
def test_failed_resolution_rolls_back_child_episode_event_and_job(
    intake,
    monkeypatch,
    operation,
    fault,
):
    data = intake[2]
    first = upsert_alert(dict(data))
    before = _snapshot()
    with monkeypatch.context() as patch:
        _inject(patch, fault)
        with pytest.raises(RuntimeError, match="injected"):
            if operation == "recovery":
                upsert_alert(dict(data, status="resolved"))
            else:
                actions.resolve_alert(first.group.id)
    assert _snapshot() == before


def test_merge_closes_source_without_transferring_its_episode(intake):
    team, _, _ = intake
    first = create_manual_alert_group(
        {"team_id": team.id, "title": "Target", "notify": False}
    )
    second = create_manual_alert_group(
        {"team_id": team.id, "title": "Source", "notify": False}
    )
    source_episode = second.current_episode
    target_episode_id = first.current_episode_id

    merged = alerts_repo.merge_alert_groups(first.id, [second.id])
    alerts_repo.merge_alert_groups(first.id, [second.id])

    assert merged.current_episode_id == target_episode_id
    source = AlertGroup.get_by_id(second.id)
    saved = AlertGroupEpisode.get_by_id(source_episode.id)
    assert saved.alert_group_id == second.id and saved.state == "merged"
    assert saved.ended_at == source.merged_at
    assert saved.end_event.event_type == "merged"
    assert source.current_episode_id is None
    assert _job(saved).requested_generation == 2
    assert len(_episodes(first.id)) == len(_episodes(second.id)) == 1


def test_merge_into_already_merged_target_returns_conflict(
    intake, client, admin_headers
):
    team, _, _ = intake
    target, source, destination = [
        create_manual_alert_group({"team_id": team.id, "title": title, "notify": False})
        for title in ("Target", "Source", "Destination")
    ]
    alerts_repo.merge_alert_groups(destination.id, [target.id])
    before = _snapshot()

    response = client.post(
        f"/api/alert-groups/{target.id}/merge",
        headers=admin_headers,
        json={"source_group_ids": [source.id]},
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "conflict"
    assert _snapshot() == before


def test_merge_failure_rolls_back_children_and_both_groups(intake, monkeypatch):
    team, _, _ = intake
    groups = [
        create_manual_alert_group({"team_id": team.id, "title": title, "notify": False})
        for title in ("One", "Two")
    ]
    before = _snapshot()
    monkeypatch.setattr(changes_repo, "request_job", _fail)
    with pytest.raises(RuntimeError, match="injected"):
        alerts_repo.merge_alert_groups(groups[0].id, [groups[1].id])
    assert _snapshot() == before


@pytest.mark.parametrize("fail", [False, True])
def test_resource_deletion_closes_episode_atomically(intake, monkeypatch, fail):
    team, route, data = intake
    first = upsert_alert(dict(data))
    heartbeat = create_heartbeat(team, route)
    heartbeat.current_alert_group = first.group.id
    heartbeat.save()
    before = _snapshot()
    if fail:
        monkeypatch.setattr(changes_repo, "request_job", _fail)
        with pytest.raises(RuntimeError, match="injected"):
            heartbeats_repo.soft_delete_heartbeat(heartbeat)
        assert _snapshot() == before
        assert not Heartbeat.get_by_id(heartbeat.id).deleted
    else:
        heartbeats_repo.soft_delete_heartbeat(heartbeat)
        episode = _episodes(first.group.id)[0]
        assert episode.state == "resolved"
        assert _job(episode).requested_generation == 2
        assert AlertGroup.get_by_id(first.group.id).current_episode_id is None
        assert Heartbeat.get_by_id(heartbeat.id).deleted


def test_team_deletion_closes_current_episode_once(intake):
    team, _, data = intake
    first = upsert_alert(dict(data))
    soft_delete_hardening.resolve_team_runtime_alerts(team.id)
    soft_delete_hardening.resolve_team_runtime_alerts(team.id)
    episode = _episodes(first.group.id)[0]
    assert episode.state == "resolved"
    assert _job(episode).requested_generation == 2
    assert Alert.get_by_id(first.alert.id).status == "resolved"


def test_resource_closure_does_not_use_a_timestamp_from_before_the_cycle(intake):
    initial = upsert_alert(dict(intake[2]))
    episode = initial.group.current_episode
    soft_delete_hardening.resolve_alert_groups_by_ids(
        [initial.group.id],
        now=episode.started_at - timedelta(seconds=1),
    )
    closed = AlertGroupEpisode.get_by_id(episode.id)
    assert closed.state == "resolved" and closed.ended_at >= closed.started_at
    assert Alert.get_by_id(initial.alert.id).resolved_at == closed.ended_at


def test_heartbeat_overdue_and_ping_close_the_same_episode(db):
    team = create_team(create_group())
    route = create_route(team, source="heartbeat")
    now = utc_now()
    heartbeat = create_heartbeat(
        team,
        route,
        status="ok",
        expected_interval_seconds=60,
        next_expected_at=now - timedelta(minutes=1),
    )
    heartbeat_service.mark_heartbeat_overdue(heartbeat, now=now)
    heartbeat = Heartbeat.get_by_id(heartbeat.id)
    episode = _episodes(heartbeat.current_alert_group_id)[0]
    heartbeat_service._resolve_current_overdue_alert(heartbeat)
    assert AlertGroupEpisode.get_by_id(episode.id).state == "resolved"
    assert _job(episode).requested_generation == 2


def test_episode_writes_require_a_transaction(intake):
    group = upsert_alert(dict(intake[2])).group
    with pytest.raises(RuntimeError, match="transaction"):
        alert_episodes_repo.open_episode(group)
    with pytest.raises(RuntimeError, match="transaction"):
        alert_episodes_repo.close_episode(group, state="resolved", ended_at=utc_now())


def test_incident_only_reopen_does_not_open_a_technical_episode(intake):
    from app.services.incidents.core import transition_incident

    team, _, data = intake
    initial = upsert_alert(dict(data))
    upsert_alert(dict(data, status="resolved"))
    incident = Incident.create(
        team=team, title="Investigation", workflow_status="resolved"
    )
    IncidentAlertGroupLink.create(incident=incident, alert_group=initial.group)
    before = [list(model.select().dicts()) for model in (AlertGroupEpisode, ChangeJob)]

    transition_incident(
        incident.id, "investigating", expected_version=incident.row_version
    )

    assert [
        list(model.select().dicts()) for model in (AlertGroupEpisode, ChangeJob)
    ] == before
    assert AlertGroup.get_by_id(initial.group.id).current_episode_id is None


def test_orchestration_resolution_closes_current_episode(intake, monkeypatch):
    from app.services.orchestration.runtime import run_event_orchestration
    from tests.orchestration.test_orchestration_runtime import _always, _publish

    team, _, data = intake
    initial = upsert_alert(dict(data))
    _publish(team.group, _always([{"type": "set_event_action", "value": "resolve"}]))
    monkeypatch.setattr(lifecycle, "run_event_orchestration", run_event_orchestration)

    resolved = upsert_alert(dict(data))

    assert resolved.group.status == "resolved"
    assert (
        AlertGroupEpisode.get_by_id(initial.group.current_episode_id).state
        == "resolved"
    )
    assert resolved.group.current_episode_id is None


@pytest.mark.parametrize("legacy", [False, True])
def test_maintenance_and_silence_preserve_the_current_episode(intake, legacy):
    from app.services.alerts.maintenance_state import reconcile_maintenance_window
    from app.services.silences import reconcile_silence
    from tests.services.test_maintenance_retroactive import _window

    team, _, data = intake
    service = create_service(team)
    first = upsert_alert(dict(data, _forced_service_id=service.id))
    group = _remove_episode_tracking(first.group) if legacy else first.group
    episode_id = group.current_episode_id
    window = _window(team, service, behavior="create_maintenance_incident")
    reconcile_maintenance_window(window)
    assert AlertGroup.get_by_id(first.group.id).status == "maintenance"
    reconcile_maintenance_window(window, now=window.ends_at + timedelta(seconds=1))
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=True,
    )
    reconcile_silence(silence)
    assert AlertGroup.get_by_id(first.group.id).status == "silenced"
    assert AlertGroup.get_by_id(first.group.id).current_episode_id == episode_id
    assert len(_episodes(first.group.id)) == (0 if legacy else 1)
    if legacy:
        assert not ChangeJob.select().exists()
    else:
        assert _job(AlertGroupEpisode.get_by_id(episode_id)).requested_generation == 1


def test_silence_release_retries_a_child_moved_after_parent_selection(
    intake, monkeypatch
):
    from app.services import silences

    team, _, data = intake
    source = upsert_alert(dict(data)).group
    target = create_manual_alert_group(
        {"team_id": team.id, "title": "Target", "notify": False}
    )
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=True,
    )
    silences.reconcile_silence(silence)

    def merge_after_selection(alert_ids):
        alerts_repo.merge_alert_groups(target.id, [source.id])
        return {source.id: AlertGroup.get_by_id(source.id)}

    with monkeypatch.context() as patch:
        patch.setattr(silences, "_lock_groups_for_alerts", merge_after_selection)
        result = silences.release_silence_applications(silence, reason="disabled")
    assert result["released"] == 0
    result = silences.release_silence_applications(silence, reason="disabled")
    assert result["released"] == result["reactivated"] == 1
    assert AlertGroup.get_by_id(source.id).current_episode_id is None
    assert (
        AlertGroup.get_by_id(target.id).current_episode_id == target.current_episode_id
    )


def test_maintenance_release_cannot_reactivate_a_merged_group(intake):
    from app.services.alerts.maintenance_state import reconcile_maintenance_window
    from tests.services.test_maintenance_retroactive import _window

    team, _, data = intake
    service = create_service(team)
    source = upsert_alert(dict(data, _forced_service_id=service.id)).group
    target = create_manual_alert_group(
        {"team_id": team.id, "title": "Target", "notify": False}
    )
    windows = [
        _window(team, service, behavior="create_maintenance_incident") for _ in range(2)
    ]
    for window in windows:
        reconcile_maintenance_window(window)
    alerts_repo.merge_alert_groups(target.id, [source.id])

    reconcile_maintenance_window(windows[0], force_release=True)

    saved = AlertGroup.get_by_id(source.id)
    assert saved.status == "merged" and saved.current_episode_id is None
    assert AlertGroupEpisode.get_by_id(source.current_episode_id).state == "merged"


@pytest.mark.parametrize("reopen", [False, True])
@pytest.mark.parametrize(
    "operation",
    [
        "record",
        "reminder",
        "schedule",
        "clear",
        "sent",
        "pause",
        "shelved_schedule",
        "shelved_reminder",
    ],
)
def test_background_notification_write_preserves_the_current_cycle(
    intake, monkeypatch, reopen, operation
):
    from app.services.alerts import maintenance_state, notification_queue, reminders

    data = intake[2]
    stale = upsert_alert(dict(data)).group
    stale.next_escalation_at = utc_now()
    upsert_alert(dict(data, status="resolved"))
    if reopen:
        upsert_alert(dict(data))
    current = AlertGroup.get_by_id(stale.id)
    before = [list(model.select().dicts()) for model in (AlertGroupEpisode, ChangeJob)]
    now = utc_now()

    if operation == "record":
        alerts_repo.record_group_notification_time(stale, now)
    elif operation == "reminder":
        alerts_repo.increment_group_reminder(stale, now)
    elif operation == "schedule":
        stale.notification_pending = False
        alerts_repo.schedule_alert_group_notification(stale, now)
    elif operation == "clear":
        alerts_repo.clear_alert_group_notification(stale)
    elif operation == "sent":
        alerts_repo.mark_alert_group_notification_sent(stale, now)
    elif operation == "pause":
        maintenance_state.pause_notification_lifecycle(stale)
    elif operation == "shelved_schedule":
        monkeypatch.setattr(
            notification_queue, "is_alert_group_shelved", lambda *a, **kw: True
        )
        notification_queue.schedule_group_notification(stale)
    else:
        monkeypatch.setattr(reminders, "is_alert_group_shelved", lambda *a, **kw: True)
        monkeypatch.setattr(alerts_repo, "list_firing_alert_groups", lambda: [stale])
        monkeypatch.setattr(alerts_repo, "get_alert_group", lambda group_id: stale)
        reminders.send_unacked_reminders()

    saved = AlertGroup.get_by_id(stale.id)
    assert (saved.status, saved.resolved_at, saved.current_episode_id) == (
        current.status,
        current.resolved_at,
        current.current_episode_id,
    )
    assert [
        list(model.select().dicts()) for model in (AlertGroupEpisode, ChangeJob)
    ] == before


@pytest.mark.parametrize("reopen", [False, True])
@pytest.mark.parametrize("mode", ["rotation", "policy", "exhausted"])
def test_background_escalation_preserves_the_current_cycle(
    intake, monkeypatch, reopen, mode
):
    from app.services.alerts import escalation
    from tests.factories import (
        create_escalation_policy,
        create_escalation_policy_rule,
        create_user,
    )

    team, _, data = intake
    user = create_user(group=team.group)
    stale = upsert_alert(dict(data)).group
    if mode == "rotation":
        team.escalation_enabled = True
        team.escalation_after_reminders = 0
        team.save()
        stale.team = team
        monkeypatch.setattr(escalation, "get_next_rotation_user", lambda *a: user)
    else:
        policy = create_escalation_policy(team)
        rule = create_escalation_policy_rule(policy, target_type="user", user=user)
        stale.escalation_policy = policy
        stale.next_escalation_at = utc_now() - timedelta(seconds=1)
        monkeypatch.setattr(
            escalation.escalation_policy_service,
            "get_next_rule_for_alert",
            lambda group: (None if mode == "exhausted" else rule, 0),
        )
    monkeypatch.setattr(escalation, "_deliver_escalation_notification", lambda group: 0)
    upsert_alert(dict(data, status="resolved"))
    if reopen:
        upsert_alert(dict(data))
    current = AlertGroup.get_by_id(stale.id)
    before = [list(model.select().dicts()) for model in (AlertGroupEpisode, ChangeJob)]

    assert escalation.maybe_escalate_alert(stale) is (mode != "exhausted")

    saved = AlertGroup.get_by_id(stale.id)
    assert (saved.status, saved.resolved_at, saved.current_episode_id) == (
        current.status,
        current.resolved_at,
        current.current_episode_id,
    )
    assert [
        list(model.select().dicts()) for model in (AlertGroupEpisode, ChangeJob)
    ] == before
