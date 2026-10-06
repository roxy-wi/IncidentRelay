from datetime import timedelta, timezone

import app.services.metrics as business_metrics
import app.services.readiness as readiness
from app.modules.common import utc_now
from app.modules.db import alerts_repo
from app.modules.db.locks_repo import touch_lock
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertNotification,
    AppLock,
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
    """Create team + route with an intake token, like the integration tests.

    The route groups by incident_key so that distinct alerts sharing the
    label land in one alert group (the supported reopen scenario).
    """
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
    """A deteriorating alert against an acknowledged group counts a reopen.

    Two alerts share one incident_key group; the second raises severity
    from warning to critical (critical outranks warning, see
    incidents_repo.priority_from_severity), so the acknowledgement is
    not preserved and the group reopens.
    """
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
    alert = Alert.get(Alert.group == group.id)

    acknowledge_alert(alert.id)
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


def _create_delivery(group, user, method, status, created_at=None):
    return UserNotificationDelivery.create(
        group=group.id,
        user=user.id,
        method=method,
        status=status,
        event_type="notification",
        scheduled_at=utc_now(),
        created_at=created_at or utc_now(),
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
        created_at=utc_now() - business_metrics.RECENT_WINDOW - timedelta(hours=1),
    )

    _, body = _scrape(client)

    metric = "incidentrelay_user_notification_deliveries_recent"

    assert sample_value(body, metric, {"method": "email", "status": "sent"}) == 2.0
    assert sample_value(body, metric, {"method": "email", "status": "failed"}) == 1.0
    assert sample_value(
        body, metric, {"method": "telegram", "status": "pending"},
    ) == 1.0
    # No deliveries for other methods — no sample at all.
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
    )

    _, body = _scrape(client)

    metric = "incidentrelay_alert_notification_errors_recent"

    # Only in-window errored deliveries are counted.
    assert sample_value(body, metric, {"provider": "telegram"}) == 1.0
    # A channel without a recorded error is not counted.
    assert sample_value(body, metric, {"provider": "slack"}) is None


def test_business_gauges_degrade_when_database_unreachable(client, monkeypatch):
    """
    A broken database must not fail the scrape: database_up reads 0,
    the delivery gauges have no samples and the heartbeat reads 0.
    Both init_database entry points are patched, the readiness probe's
    and the notification gauges'.
    """
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


def test_scheduler_heartbeat_job_records_lock(db):
    """The heartbeat job writes the never-released scheduler lock row."""
    result = scheduler_heartbeat_job()

    assert result == {"heartbeat": 1}

    row = AppLock.get_or_none(
        AppLock.name == business_metrics.SCHEDULER_HEARTBEAT_LOCK_NAME,
    )

    assert row is not None
    assert row.owner.startswith("scheduler:")


def test_touch_lock_creates_then_refreshes(db):
    """touch_lock upserts in place instead of stacking rows."""
    touch_lock("metrics_test_heartbeat", owner="first", ttl_seconds=60)
    touch_lock("metrics_test_heartbeat", owner="second", ttl_seconds=60)

    rows = AppLock.select().where(AppLock.name == "metrics_test_heartbeat")

    assert rows.count() == 1
    assert rows.get().owner == "second"
