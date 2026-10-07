from datetime import timedelta, timezone

import app.services.metrics as business_metrics
import app.services.readiness as readiness
from app.modules.common import utc_now
from app.modules.db import alerts_repo
from app.modules.db.locks_repo import touch_lock
from app.modules.db.models import (
    AlertGroup,
    AlertNotification,
    AppLock,
    EventOrchestration,
    EventOrchestrationVersion,
    PendingOrchestratedEvent,
    UserNotificationDelivery,
)
from app.services.alerts.actions import acknowledge_alert
from app.services.integrations.auth import hash_token
from app.services.scheduler import scheduler_heartbeat_job
from app.settings import Config
from tests.factories import (
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
)
from tests.metrics.exposition import sample_value


def _enable(monkeypatch, token=""):
    """Enable the metrics endpoint for one test."""
    monkeypatch.setattr(Config, "METRICS_ENABLED", True)
    monkeypatch.setattr(Config, "METRICS_AUTH_TOKEN", token)


def _scrape(client):
    """Scrape /metrics and return (response, body)."""
    response = client.get("/metrics")

    assert response.status_code == 200

    return response, response.get_data(as_text=True)


def _grafana_payload(severity="critical"):
    """Minimal valid Grafana payload, mirroring tests/integrations."""
    return {
        "receiver": "incidentrelay",
        "status": "firing",
        "orgId": 1,
        "groupKey": "{}:{alertname=\"DiskFull\"}",
        "groupLabels": {
            "alertname": "DiskFull",
        },
        "commonLabels": {
            "team": "sre",
            "environment": "production",
        },
        "commonAnnotations": {
            "runbook_url": "https://example.com/runbooks/disk",
        },
        "externalURL": "https://grafana.example.com/",
        "title": "[FIRING:1] DiskFull",
        "state": "alerting",
        "message": "Grafana notification",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "DiskFull",
                    "severity": severity,
                    "instance": "host1",
                    "grafana_folder": "Infrastructure",
                    "__alert_rule_uid__": "disk-full-rule",
                },
                "annotations": {
                    "summary": "Disk is full",
                    "description": "/var is 95% full",
                },
                "startsAt": "2026-06-21T10:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": (
                    "https://grafana.example.com/alerting/"
                    "grafana/disk-full-rule/view"
                ),
                "fingerprint": "grafana-disk-full-host1",
            },
        ],
    }


def _intake_route(source="grafana", token="route-token"):
    """Create team + route with an intake token, like the integration tests."""
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    create_route(
        team,
        source=source,
        token_hash=hash_token(token),
        group_by=["incident_key"],
    )

    return team


# ---------------------------------------------------------------------------
# Counters: alerts received
# ---------------------------------------------------------------------------


def test_intake_counts_alerts_by_source(client, monkeypatch):
    """Real integration intake must land in alerts_received{source}."""
    _enable(monkeypatch)
    _intake_route()

    before = business_metrics.REGISTRY.get_sample_value(
        "incidentrelay_alerts_received_total",
        {"source": "grafana"},
    ) or 0.0

    response = client.post(
        "/api/integrations/grafana",
        headers={"Authorization": "Bearer route-token"},
        json=_grafana_payload(),
    )

    assert response.status_code == 200

    after = business_metrics.REGISTRY.get_sample_value(
        "incidentrelay_alerts_received_total",
        {"source": "grafana"},
    )

    assert after == before + 1.0


def test_record_helpers_are_noops_when_metrics_disabled(monkeypatch):
    """With metrics disabled the record helpers must not touch counters."""
    monkeypatch.setattr(Config, "METRICS_ENABLED", False)

    before = (
        business_metrics.REGISTRY.get_sample_value(
            "incidentrelay_alerts_received_total",
            {"source": "grafana"},
        )
        or 0.0
    )

    business_metrics.record_alert_received("grafana")
    business_metrics.record_alert_group_action("created")

    after = (
        business_metrics.REGISTRY.get_sample_value(
            "incidentrelay_alerts_received_total",
            {"source": "grafana"},
        )
        or 0.0
    )

    assert after == before


# ---------------------------------------------------------------------------
# Counters: alert group lifecycle
# ---------------------------------------------------------------------------


def test_alert_group_action_counters_follow_repo_transitions(client, monkeypatch):
    """created/acknowledged/resolved land on the repo-level hook points."""
    _enable(monkeypatch)
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    def action_total(action):
        return (
            business_metrics.REGISTRY.get_sample_value(
                "incidentrelay_alert_group_actions_total",
                {"action": action},
            )
            or 0.0
        )

    created_before = action_total("created")
    created = alerts_repo.create_alert_group(
        team=team.id,
        source="manual",
        group_key="metrics-test-key",
        title="Metrics test group",
        status="firing",
        first_seen_at=utc_now(),
        last_seen_at=utc_now(),
    )
    assert action_total("created") == created_before + 1.0

    acknowledged_before = action_total("acknowledged")
    alerts_repo.acknowledge_alert_group(created.id)
    assert action_total("acknowledged") == acknowledged_before + 1.0

    resolved_before = action_total("resolved")
    alerts_repo.resolve_alert_group(created.id)
    assert action_total("resolved") == resolved_before + 1.0


def test_reopen_counter_after_acknowledged_group_reopens(client, monkeypatch):
    """A deteriorating alert against an acknowledged group counts a reopen."""
    _enable(monkeypatch)
    _intake_route()

    def payload(fingerprint, severity):
        payload = _grafana_payload(severity=severity)
        payload["alerts"][0]["labels"]["incident_key"] = "disk-full"
        payload["alerts"][0]["fingerprint"] = fingerprint
        return payload

    response = client.post(
        "/api/integrations/grafana",
        headers={"Authorization": "Bearer route-token"},
        json=payload("disk-full-host1", "warning"),
    )
    assert response.status_code == 200

    group = AlertGroup.get(AlertGroup.source == "grafana")

    acknowledge_alert(group.id)
    assert AlertGroup.get_by_id(group.id).status == "acknowledged"

    reopened_before = (
        business_metrics.REGISTRY.get_sample_value(
            "incidentrelay_alert_group_actions_total",
            {"action": "reopened"},
        )
        or 0.0
    )

    response = client.post(
        "/api/integrations/grafana",
        headers={"Authorization": "Bearer route-token"},
        json=payload("disk-full-host2", "critical"),
    )
    assert response.status_code == 200

    reopened_after = business_metrics.REGISTRY.get_sample_value(
        "incidentrelay_alert_group_actions_total",
        {"action": "reopened"},
    )

    assert reopened_after == reopened_before + 1.0
    assert AlertGroup.get_by_id(group.id).status == "firing"


# ---------------------------------------------------------------------------
# Gauges: notification deliveries (database-derived)
# ---------------------------------------------------------------------------


def _create_delivery(
    group,
    user,
    method,
    status,
    *,
    scheduled_at=None,
    created_at=None,
    updated_at=None,
):
    now = utc_now()
    return UserNotificationDelivery.create(
        group=group.id,
        user=user.id,
        method=method,
        status=status,
        event_type="notification",
        scheduled_at=scheduled_at or now,
        created_at=created_at or updated_at or now,
        updated_at=updated_at or now,
    )


def _alert_group_for_deliveries():
    """Build team + a real AlertGroup + one user for delivery rows."""
    tenant = create_group(slug="platform")
    team = create_team(tenant, slug="sre")

    alert_group = alerts_repo.create_alert_group(
        team=team.id,
        source="manual",
        group_key="deliveries-key",
        title="Deliveries test group",
        status="firing",
        first_seen_at=utc_now(),
        last_seen_at=utc_now(),
    )

    user = create_user(username="metrics-user", group=tenant)

    return alert_group, user


def test_user_notification_deliveries_recent_gauge(client, monkeypatch):
    """Deliveries from the last 24 hours are grouped by method and outcome."""
    _enable(monkeypatch)
    alert_group, user = _alert_group_for_deliveries()

    _create_delivery(alert_group, user, "email", "sent")
    _create_delivery(alert_group, user, "email", "sent")
    _create_delivery(alert_group, user, "email", "failed")
    _create_delivery(alert_group, user, "telegram", "pending")
    _create_delivery(
        alert_group,
        user,
        "email",
        "sent",
        updated_at=utc_now() - business_metrics.RECENT_WINDOW - timedelta(hours=1),
    )
    # Old row that failed just now still counts (window on updated_at).
    _create_delivery(
        alert_group,
        user,
        "email",
        "failed",
        created_at=(
            utc_now() - business_metrics.RECENT_WINDOW - timedelta(hours=48)
        ),
        updated_at=utc_now(),
    )

    _, body = _scrape(client)

    metric = "incidentrelay_user_notification_deliveries_recent"

    assert sample_value(body, metric, {"method": "email", "status": "sent"}) == 2.0
    assert sample_value(body, metric, {"method": "email", "status": "failed"}) == 2.0
    assert sample_value(
        body, metric, {"method": "telegram", "status": "pending"},
    ) == 1.0
    # No deliveries for other methods, no sample at all.
    assert sample_value(body, metric, {"method": "email", "status": "pending"}) is None


def test_alert_notification_errors_recent_gauge(client, monkeypatch):
    """Errored notification deliveries are counted per provider."""
    _enable(monkeypatch)
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")

    failing = create_channel(group, team=team, channel_type="telegram", config={})
    healthy = create_channel(group, team=team, channel_type="slack", config={})

    AlertNotification.create(
        channel=failing,
        provider="telegram",
        last_error="connection refused",
    )
    AlertNotification.create(
        channel=healthy,
        provider="slack",
        last_error=None,
    )
    AlertNotification.create(
        channel=failing,
        provider="telegram",
        last_error="timeout",
        created_at=utc_now() - business_metrics.RECENT_WINDOW - timedelta(hours=1),
        updated_at=utc_now() - business_metrics.RECENT_WINDOW - timedelta(hours=1),
    )
    # Old row that failed just now still counts (window on updated_at).
    AlertNotification.create(
        channel=failing,
        provider="telegram",
        last_error="connection refused",
        created_at=utc_now() - business_metrics.RECENT_WINDOW - timedelta(hours=48),
        updated_at=utc_now(),
    )

    _, body = _scrape(client)

    metric = "incidentrelay_alert_notification_errors_recent"

    # Only in-window errored deliveries are counted.
    assert sample_value(body, metric, {"provider": "telegram"}) == 2.0
    # A channel without a recorded error is not counted.
    assert sample_value(body, metric, {"provider": "slack"}) is None


def test_user_notification_queue_backlog_gauges(client, monkeypatch):
    """Only due pending work and in-flight processing contribute to backlog."""
    _enable(monkeypatch)
    alert_group, user = _alert_group_for_deliveries()
    now = utc_now()

    _create_delivery(
        alert_group,
        user,
        "email",
        "pending",
        scheduled_at=now - timedelta(seconds=120),
        updated_at=now - timedelta(seconds=120),
    )
    _create_delivery(
        alert_group,
        user,
        "email",
        "pending",
        scheduled_at=now + timedelta(minutes=10),
    )
    _create_delivery(
        alert_group,
        user,
        "voice_call",
        "processing",
        scheduled_at=now - timedelta(seconds=60),
        updated_at=now - timedelta(seconds=45),
    )

    _, body = _scrape(client)

    assert sample_value(
        body,
        "incidentrelay_user_notification_queue_depth",
        {"state": "due"},
    ) == 1.0
    assert sample_value(
        body,
        "incidentrelay_user_notification_queue_depth",
        {"state": "processing"},
    ) == 1.0

    due_age = sample_value(
        body,
        "incidentrelay_user_notification_queue_oldest_age_seconds",
        {"state": "due"},
    )
    processing_age = sample_value(
        body,
        "incidentrelay_user_notification_queue_oldest_age_seconds",
        {"state": "processing"},
    )

    assert 100 <= due_age <= 180
    assert 30 <= processing_age <= 90


def test_orchestration_backlog_gauges(client, monkeypatch):
    """Future paused events count in inventory but not in due age."""
    _enable(monkeypatch)
    group = create_group(slug="metrics-orchestration")
    orchestration = EventOrchestration.create(
        group=group.id,
        name="Metrics backlog",
    )
    version = EventOrchestrationVersion.create(
        orchestration=orchestration.id,
        version_number=1,
    )
    now = utc_now()

    def create_pending(dedup_key, status, activation_at, next_attempt_at=None):
        return PendingOrchestratedEvent.create(
            group=group.id,
            orchestration=orchestration.id,
            version=version.id,
            source="alertmanager",
            dedup_key=dedup_key,
            normalized_event_json={},
            context_json={},
            activation_at=activation_at,
            next_attempt_at=next_attempt_at,
            status=status,
        )

    create_pending("due", "pending", now - timedelta(seconds=120))
    create_pending("future", "pending", now + timedelta(minutes=10))
    create_pending("activating", "activating", now - timedelta(seconds=20))
    create_pending("failed", "failed", now - timedelta(minutes=5))

    _, body = _scrape(client)

    for status, expected in (
        ("pending", 2.0),
        ("activating", 1.0),
        ("failed", 1.0),
    ):
        assert sample_value(
            body,
            "incidentrelay_orchestration_pending_events",
            {"status": status},
        ) == expected

    oldest_due_age = sample_value(
        body,
        "incidentrelay_orchestration_oldest_due_age_seconds",
        {},
    )
    assert 100 <= oldest_due_age <= 180


def test_business_gauges_degrade_when_database_unreachable(client, monkeypatch):
    """A broken database reads database_up 0 and empty gauges, not a 500."""
    _enable(monkeypatch)

    def broken_init():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(business_metrics, "init_database", broken_init)
    monkeypatch.setattr(readiness, "init_database", broken_init)

    _, body = _scrape(client)

    assert sample_value(
        body,
        "incidentrelay_database_up",
        {},
    ) == 0.0

    for name, labels in (
        (
            "incidentrelay_user_notification_deliveries_recent",
            {"method": "email", "status": "sent"},
        ),
        (
            "incidentrelay_alert_notification_errors_recent",
            {"provider": "telegram"},
        ),
    ):
        assert sample_value(body, name, labels) is None, name

    assert sample_value(
        body,
        "incidentrelay_scheduler_last_run_timestamp_seconds",
        {},
    ) == 0.0


# ---------------------------------------------------------------------------
# Gauge: scheduler heartbeat
# ---------------------------------------------------------------------------


def test_scheduler_heartbeat_gauge_absent_then_present(client, monkeypatch):
    """Without a heartbeat the gauge reads 0; a lock row carries unix time."""
    _enable(monkeypatch)

    _, body = _scrape(client)
    assert sample_value(
        body,
        "incidentrelay_scheduler_last_run_timestamp_seconds",
        {},
    ) == 0.0

    updated_at = utc_now() - timedelta(seconds=45)
    AppLock.create(
        name=business_metrics.SCHEDULER_HEARTBEAT_LOCK_NAME,
        owner="scheduler:test",
        expires_at=utc_now() + timedelta(seconds=60),
        updated_at=updated_at,
    )

    _, body = _scrape(client)
    value = sample_value(
        body,
        "incidentrelay_scheduler_last_run_timestamp_seconds",
        {},
    )

    expected = updated_at.replace(tzinfo=timezone.utc).timestamp()
    assert abs(value - expected) < 2.0


def test_worker_heartbeat_gauge_reports_worker_roles(client, monkeypatch):
    _enable(monkeypatch)
    now = utc_now()

    AppLock.create(
        name=business_metrics.WORKER_HEARTBEAT_LOCK_NAMES["scheduler"],
        owner="scheduler:test",
        expires_at=now + timedelta(seconds=120),
        updated_at=now - timedelta(seconds=10),
    )
    AppLock.create(
        name=business_metrics.WORKER_HEARTBEAT_LOCK_NAMES["telegram"],
        owner="telegram:test",
        expires_at=now + timedelta(seconds=120),
        updated_at=now - timedelta(seconds=20),
    )

    _, body = _scrape(client)

    scheduler_value = sample_value(
        body,
        "incidentrelay_worker_last_seen_timestamp_seconds",
        {"worker": "scheduler"},
    )
    telegram_value = sample_value(
        body,
        "incidentrelay_worker_last_seen_timestamp_seconds",
        {"worker": "telegram"},
    )
    slack_value = sample_value(
        body,
        "incidentrelay_worker_last_seen_timestamp_seconds",
        {"worker": "slack"},
    )
    legacy_scheduler_value = sample_value(
        body,
        "incidentrelay_scheduler_last_run_timestamp_seconds",
        {},
    )

    assert abs(scheduler_value - legacy_scheduler_value) < 0.001
    assert scheduler_value > 0
    assert telegram_value > 0
    assert slack_value == 0


def test_record_worker_heartbeat_persists_worker_lock(db, monkeypatch):
    monkeypatch.setattr(
        business_metrics,
        "_WORKER_HEARTBEAT_LAST_ATTEMPT",
        {},
    )

    assert business_metrics.record_worker_heartbeat(
        "slack",
        min_interval_seconds=0,
    ) is True

    row = AppLock.get(
        AppLock.name
        == business_metrics.WORKER_HEARTBEAT_LOCK_NAMES["slack"]
    )
    assert row.owner.startswith("slack:")
    assert row.updated_at is not None


def test_scheduler_heartbeat_job_records_lock(db):
    """The heartbeat job writes the never-released scheduler lock row."""
    result = scheduler_heartbeat_job()

    assert result == {"heartbeat": 1}

    row = AppLock.get_or_none(
        AppLock.name == business_metrics.SCHEDULER_HEARTBEAT_LOCK_NAME,
    )

    assert row is not None
    assert row.owner.startswith("scheduler:")


def test_scheduler_registers_heartbeat_job_only_when_metrics_enabled(monkeypatch):
    """The scheduler registers the heartbeat job only while metrics are on."""

    from app.services import scheduler as scheduler_module

    registered = []

    class _FakeScheduler:
        running = False

        def add_job(self, job, *args, **kwargs):
            registered.append(kwargs.get("id"))

        def start(self):
            self.running = True

        def shutdown(self, wait=False):
            self.running = False

    monkeypatch.setattr(scheduler_module, "_scheduler", None)
    monkeypatch.setattr(scheduler_module, "BackgroundScheduler", _FakeScheduler)

    try:
        monkeypatch.setattr(scheduler_module.Config, "METRICS_ENABLED", False)
        scheduler_module.start_scheduler()

        assert "scheduler_heartbeat_job" not in registered
        assert "reminder_job" in registered

        scheduler_module.stop_scheduler()

        monkeypatch.setattr(scheduler_module.Config, "METRICS_ENABLED", True)
        scheduler_module.start_scheduler()

        assert "scheduler_heartbeat_job" in registered
    finally:
        scheduler_module.stop_scheduler()


def test_touch_lock_creates_then_refreshes(db):
    """touch_lock upserts in place instead of stacking rows."""
    touch_lock("metrics_test_heartbeat", owner="first", ttl_seconds=60)
    touch_lock("metrics_test_heartbeat", owner="second", ttl_seconds=60)

    rows = AppLock.select().where(AppLock.name == "metrics_test_heartbeat")

    assert rows.count() == 1
    assert rows.get().owner == "second"
