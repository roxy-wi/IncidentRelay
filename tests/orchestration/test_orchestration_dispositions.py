from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import (
    Alert,
    AlertGroup,
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationIntakeToken,
    PendingOrchestratedEvent,
)
from app.modules.db.orchestrations_repo import (
    OrchestrationValidationError,
    create_orchestration,
    get_or_create_draft,
    publish_draft,
    replace_draft_rules,
    set_runtime_state,
)
from app.services.alerts.lifecycle import upsert_alert
from app.services.serializers.alerts import serialize_alert_group
from app.services.serializers.incidents import serialize_incident_alert
from app.services.orchestration.metrics import get_orchestration_disposition_metrics
from app.services.orchestration.pending import (
    cleanup_orchestration_retention,
    process_due_pending_events,
    resolve_pending_event,
    retry_failed_pending_event,
)
from tests.factories import create_group, create_route, create_team, create_user


@pytest.fixture(autouse=True)
def orchestration_tables(db):
    db.create_tables(
        [
            EventOrchestration,
            EventOrchestrationVersion,
            EventOrchestrationRule,
            OrchestrationIntakeToken,
            OrchestrationExecution,
            PendingOrchestratedEvent,
        ],
        safe=True,
    )
    PendingOrchestratedEvent.delete().execute()
    OrchestrationExecution.delete().execute()
    EventOrchestrationRule.delete().execute()
    EventOrchestrationVersion.delete().execute()
    OrchestrationIntakeToken.delete().execute()
    EventOrchestration.delete().execute()
    yield


def _publish(group, actions):
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="disposition-test",
        scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [
            {
                "name": "always",
                "condition_tree": {},
                "actions": actions,
                "processing_mode": "continue",
            }
        ],
    )
    publish_draft(
        orchestration.id,
        actor_id=user.id,
        confirm_catch_all_drop=True,
    )
    return set_runtime_state(
        orchestration.id,
        enabled=True,
        mode="active",
        compatibility_mode="hybrid",
    )


def _alert_data(route, dedup_key, *, status="firing"):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": dedup_key,
        "dedup_key": dedup_key,
        "title": "Orchestration disposition",
        "message": "test payload",
        "severity": "warning",
        "status": status,
        "labels": {"alertname": "OrchestrationDisposition"},
        "payload": {"safe": True},
        "raw": {"authorization": "Bearer must-not-be-persisted"},
    }


def test_drop_keeps_short_lived_execution_without_creating_alert(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "drop", "reason": "ignored {{ event.title }}"}])

    result = upsert_alert(_alert_data(route, "drop-1"))

    assert result.outcome == "dropped"
    assert result.group is None
    assert result.alert is None
    assert Alert.select().count() == 0
    assert AlertGroup.select().count() == 0

    execution = OrchestrationExecution.get(
        OrchestrationExecution.event_fingerprint == "drop-1"
    )
    assert execution.disposition == "drop"
    assert execution.expires_at is not None
    assert execution.alert_id is None
    assert execution.alert_group_id is None


def test_suppress_creates_incident_without_scheduling_notifications(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "suppress", "reason": "maintenance-like"}])
    scheduled = []

    monkeypatch.setattr(
        "app.services.alerts.lifecycle.schedule_group_notification",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )

    result = upsert_alert(_alert_data(route, "suppress-1"))

    assert result.group is not None
    assert result.alert is not None
    assert result.group.orchestration_suppressed is True
    assert result.group.orchestration_suppress_reason == "maintenance-like"
    assert result.alert.orchestration_suppressed is True
    assert result.alert.orchestration_suppress_reason == "maintenance-like"
    assert result.group.next_escalation_at is None
    assert result.alert.next_escalation_at is None
    assert result.group.notification_pending is False
    assert scheduled == []

    group_payload = serialize_alert_group(result.group)
    alert_payload = serialize_incident_alert(result.alert)
    assert group_payload["orchestration_suppressed"] is True
    assert group_payload["orchestration_suppress_reason"] == "maintenance-like"
    assert alert_payload["orchestration_suppressed"] is True
    assert alert_payload["orchestration_suppress_reason"] == "maintenance-like"


def test_pause_creates_one_pending_row_and_preserves_first_activation(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        [
            {
                "type": "pause",
                "seconds": 120,
                "retrigger": "preserve",
                "reason": "waiting for confirmation",
            }
        ],
    )

    first = upsert_alert(_alert_data(route, "pause-preserve-1"))
    pending = PendingOrchestratedEvent.get()
    fixed_activation = utc_now() + timedelta(minutes=10)
    pending.activation_at = fixed_activation
    pending.save(only=[PendingOrchestratedEvent.activation_at])

    second = upsert_alert(_alert_data(route, "pause-preserve-1"))
    pending = PendingOrchestratedEvent.get_by_id(pending.id)

    assert first.outcome == "paused"
    assert second.outcome == "paused"
    assert PendingOrchestratedEvent.select().count() == 1
    assert pending.status == "pending"
    assert pending.activation_at == fixed_activation
    assert pending.context_json["runtime"]["disposition_reason"] == "waiting for confirmation"
    assert "raw" not in pending.normalized_event_json
    assert Alert.select().count() == 0
    assert AlertGroup.select().count() == 0


def test_pause_reset_restarts_activation_window(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        [{"type": "pause", "seconds": 120, "retrigger": "reset"}],
    )

    upsert_alert(_alert_data(route, "pause-reset-1"))
    pending = PendingOrchestratedEvent.get()
    old_activation = utc_now() - timedelta(seconds=1)
    pending.activation_at = old_activation
    pending.save(only=[PendingOrchestratedEvent.activation_at])

    upsert_alert(_alert_data(route, "pause-reset-1"))
    pending = PendingOrchestratedEvent.get_by_id(pending.id)

    assert pending.activation_at > old_activation
    assert pending.activation_at > utc_now() + timedelta(seconds=100)


def test_resolve_before_pause_activation_creates_no_incident(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "pause", "seconds": 120}])

    upsert_alert(_alert_data(route, "pause-resolve-1"))
    result = upsert_alert(
        _alert_data(route, "pause-resolve-1", status="resolved")
    )
    pending = PendingOrchestratedEvent.get()

    assert result.outcome == "resolved_before_activation"
    assert pending.status == "resolved"
    assert pending.active_key is None
    assert pending.resolved_at is not None
    assert Alert.select().count() == 0
    assert AlertGroup.select().count() == 0


def test_due_pause_activation_enters_normal_lifecycle_once(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "pause", "seconds": 120}])

    upsert_alert(_alert_data(route, "pause-activate-1"))
    pending = PendingOrchestratedEvent.get()
    pending.activation_at = utc_now() - timedelta(seconds=1)
    pending.save(only=[PendingOrchestratedEvent.activation_at])

    first = process_due_pending_events(now=utc_now())
    second = process_due_pending_events(now=utc_now())
    pending = PendingOrchestratedEvent.get_by_id(pending.id)

    assert first == {"processed": 1, "activated": 1, "failed": 0, "requeued": 0}
    assert second == {"processed": 0, "activated": 0, "failed": 0, "requeued": 0}
    assert pending.status == "activated"
    assert pending.active_key is None
    assert pending.activated_at is not None
    assert Alert.select().where(Alert.dedup_key == "pause-activate-1").count() == 1
    assert AlertGroup.select().count() == 1

    execution = OrchestrationExecution.get(
        OrchestrationExecution.event_fingerprint == "pause-activate-1"
    )
    assert execution.alert_id is not None
    assert execution.alert_group_id is not None


def test_failed_activation_is_requeued_and_can_be_retried(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "pause", "seconds": 120}])

    upsert_alert(_alert_data(route, "pause-failure-1"))
    pending = PendingOrchestratedEvent.get()
    pending.activation_at = utc_now() - timedelta(seconds=1)
    pending.save(only=[PendingOrchestratedEvent.activation_at])

    monkeypatch.setattr(
        "app.services.alerts.lifecycle._upsert_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret token=hidden")),
    )

    processed = process_due_pending_events(now=utc_now())
    pending = PendingOrchestratedEvent.get_by_id(pending.id)

    assert processed["failed"] == 1
    assert pending.status == "pending"
    assert pending.attempts == 1
    assert pending.next_attempt_at is not None
    assert "secret token=hidden" not in (pending.last_error or "")

    pending.status = "failed"
    pending.next_attempt_at = None
    pending.save()
    assert retry_failed_pending_event(pending.id, now=utc_now()) is True
    pending = PendingOrchestratedEvent.get_by_id(pending.id)
    assert pending.status == "pending"
    assert pending.attempts == 0


def test_retrigger_during_activation_does_not_steal_worker_claim(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "pause", "seconds": 120}])

    upsert_alert(_alert_data(route, "pause-claimed-retrigger-1"))
    pending = PendingOrchestratedEvent.get()
    pending.status = "activating"
    pending.claim_token = "live-claim"
    pending.claimed_at = utc_now()
    pending.save()

    repeated = _alert_data(route, "pause-claimed-retrigger-1")
    repeated["message"] = "newest payload"
    result = upsert_alert(repeated)
    pending = PendingOrchestratedEvent.get_by_id(pending.id)

    assert result.outcome == "paused"
    assert pending.status == "activating"
    assert pending.claim_token == "live-claim"
    assert pending.claimed_at is not None
    assert pending.normalized_event_json["message"] == "newest payload"


def test_resolve_winning_after_claim_cancels_activation(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "pause", "seconds": 120}])

    upsert_alert(_alert_data(route, "pause-claim-resolve-1"))
    pending = PendingOrchestratedEvent.get()
    pending.activation_at = utc_now() - timedelta(seconds=1)
    pending.save(only=[PendingOrchestratedEvent.activation_at])

    from app.services.orchestration import pending as pending_service

    original_claim_one = pending_service._claim_one

    def claim_then_resolve(row_id, *, now):
        claimed = original_claim_one(row_id, now=now)
        assert claimed is not None
        resolved = resolve_pending_event(
            group_id=group.id,
            source="alertmanager",
            dedup_key="pause-claim-resolve-1",
            now=now,
        )
        assert resolved is not None
        return claimed

    monkeypatch.setattr(pending_service, "_claim_one", claim_then_resolve)

    processed = process_due_pending_events(now=utc_now())
    pending = PendingOrchestratedEvent.get_by_id(pending.id)

    assert processed == {"processed": 1, "activated": 0, "failed": 0, "requeued": 0}
    assert pending.status == "resolved"
    assert pending.active_key is None
    assert Alert.select().count() == 0
    assert AlertGroup.select().count() == 0


def test_stale_activation_claim_is_requeued(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "pause", "seconds": 120}])

    upsert_alert(_alert_data(route, "pause-stale-1"))
    pending = PendingOrchestratedEvent.get()
    pending.status = "activating"
    pending.claim_token = "stale"
    pending.claimed_at = utc_now() - timedelta(hours=1)
    pending.activation_at = utc_now() + timedelta(hours=1)
    pending.save()

    result = process_due_pending_events(now=utc_now())
    pending = PendingOrchestratedEvent.get_by_id(pending.id)

    assert result["requeued"] == 1
    assert pending.status == "pending"
    assert pending.claim_token is None
    assert pending.claimed_at is None


def test_retention_cleanup_removes_expired_drop_trace_and_terminal_pause(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "drop"}])

    upsert_alert(_alert_data(route, "drop-expired-1"))
    execution = OrchestrationExecution.get()
    execution.expires_at = utc_now() - timedelta(seconds=1)
    execution.save(only=[OrchestrationExecution.expires_at])

    orchestration = EventOrchestration.get()
    pending = PendingOrchestratedEvent.create(
        group=group.id,
        orchestration=orchestration.id,
        version=orchestration.active_version_id,
        route=route.id,
        source="alertmanager",
        dedup_key="terminal-old",
        normalized_event_json={},
        context_json={},
        activation_at=utc_now() - timedelta(days=60),
        status="resolved",
        updated_at=utc_now() - timedelta(days=60),
    )

    result = cleanup_orchestration_retention(now=utc_now())

    assert result == {
        "executions_deleted": 1,
        "pending_events_deleted": 1,
        "webhook_executions_deleted": 0,
    }
    assert OrchestrationExecution.get_or_none(OrchestrationExecution.id == execution.id) is None
    assert PendingOrchestratedEvent.get_or_none(PendingOrchestratedEvent.id == pending.id) is None


def test_disposition_metrics_count_executions_and_pending_states(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, [{"type": "pause", "seconds": 120}])

    upsert_alert(_alert_data(route, "pause-metrics-1"))
    metrics = get_orchestration_disposition_metrics(group_id=group.id)

    assert metrics["executions_total"] == 1
    assert metrics["dispositions"]["pause"] == 1
    assert metrics["pending_events_total"] == 1
    assert metrics["pending_statuses"]["pending"] == 1
    assert metrics["dropped_trace_retention_days"] > 0


def test_catch_all_drop_requires_explicit_publish_confirmation(db):
    group = create_group()
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="catch-all-drop-confirmation",
        scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [{
            "name": "drop everything",
            "condition_tree": {},
            "actions": [{"type": "drop"}],
            "processing_mode": "continue",
        }],
    )

    with pytest.raises(OrchestrationValidationError, match="explicit publish confirmation"):
        publish_draft(orchestration.id, actor_id=user.id)

    published = publish_draft(
        orchestration.id,
        actor_id=user.id,
        confirm_catch_all_drop=True,
    )
    assert published.status == "published"


@pytest.mark.parametrize(
    "condition_tree",
    [
        {"all": []},
        {"none": []},
        {"all": [{}, {"all": []}]},
        {"any": [{"field": "event.severity", "operator": "equals", "value": "critical"}, {}]},
    ],
)
def test_logically_catch_all_drop_requires_confirmation(db, condition_tree):
    group = create_group()
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="logical-catch-all-drop",
        scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [{
            "name": "drop everything",
            "condition_tree": condition_tree,
            "actions": [{"type": "drop"}],
            "processing_mode": "continue",
        }],
    )

    with pytest.raises(OrchestrationValidationError, match="explicit publish confirmation"):
        publish_draft(orchestration.id, actor_id=user.id)
