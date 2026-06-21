import hashlib
import hmac
import json

from app.services.integrations.normalizers.sentry import normalize_sentry
from app.services.integrations.sentry import verify_sentry_signature
from tests.factories import create_group, create_route, create_team, unique


def sentry_body(payload):
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def sentry_signature(secret, raw_body):
    return hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()


def sentry_issue_alert_payload(action="triggered"):
    return {
        "action": action,
        "data": {
            "event_alert": {
                "id": "event-rule-1",
                "name": "New issue alert",
            },
            "issue": {
                "id": "12345",
                "shortId": "BACKEND-1",
                "title": "ZeroDivisionError",
                "level": "error",
                "culprit": "api.views.checkout",
                "permalink": "https://sentry.example.com/issues/12345/",
            },
            "event": {
                "event_id": "event-abc",
                "environment": "production",
                "message": "division by zero",
            },
            "project": {
                "slug": "backend-api",
                "name": "Backend API",
            },
            "organization": {
                "slug": "acme",
                "name": "Acme",
            },
        },
    }


def sentry_metric_alert_payload(action="resolved"):
    return {
        "action": action,
        "data": {
            "metric_alert": {
                "id": "metric-alert-7",
                "name": "High error rate",
                "status": action,
                "web_url": "https://sentry.example.com/alerts/metric/7/",
            },
            "project": {
                "slug": "backend-api",
                "name": "Backend API",
            },
            "organization": {
                "slug": "acme",
                "name": "Acme",
            },
        },
    }


def test_verify_sentry_signature_accepts_valid_signature():
    secret = "sentry-secret"
    raw_body = b'{"action":"triggered"}'
    signature = sentry_signature(secret, raw_body)

    assert verify_sentry_signature(secret, raw_body, signature) is True


def test_verify_sentry_signature_rejects_invalid_signature():
    secret = "sentry-secret"
    raw_body = b'{"action":"triggered"}'
    signature = sentry_signature(secret, raw_body)

    assert verify_sentry_signature(secret, raw_body + b"x", signature) is False
    assert verify_sentry_signature("other-secret", raw_body, signature) is False
    assert verify_sentry_signature(secret, raw_body, "bad-signature") is False


def test_normalize_sentry_event_alert_triggered():
    alerts = normalize_sentry(
        sentry_issue_alert_payload(action="triggered"),
        headers={"Sentry-Hook-Resource": "event_alert"},
    )

    assert len(alerts) == 1

    alert = alerts[0]

    assert alert["source"] == "sentry"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"
    assert alert["dedup_key"] == "sentry:issue:12345"
    assert alert["external_id"] == "12345"
    assert alert["title"] == "ZeroDivisionError"
    assert alert["message"] == "division by zero"
    assert alert["labels"]["alertname"] == "SentryIssueAlert"
    assert alert["labels"]["sentry_resource"] == "event_alert"
    assert alert["labels"]["sentry_action"] == "triggered"
    assert alert["labels"]["organization_slug"] == "acme"
    assert alert["labels"]["project_slug"] == "backend-api"
    assert alert["labels"]["issue_id"] == "12345"
    assert alert["labels"]["issue_short_id"] == "BACKEND-1"
    assert alert["labels"]["environment"] == "production"
    assert alert["labels"]["sentry_url"] == "https://sentry.example.com/issues/12345/"


def test_normalize_sentry_issue_resolved_resolves_same_dedup_key():
    firing = normalize_sentry(
        sentry_issue_alert_payload(action="triggered"),
        headers={"Sentry-Hook-Resource": "event_alert"},
    )[0]

    resolved_payload = sentry_issue_alert_payload(action="resolved")
    resolved_payload["data"].pop("event_alert")
    resolved_payload["data"]["issue"]["status"] = "resolved"

    resolved = normalize_sentry(
        resolved_payload,
        headers={"Sentry-Hook-Resource": "issue"},
    )[0]

    assert firing["dedup_key"] == "sentry:issue:12345"
    assert resolved["dedup_key"] == "sentry:issue:12345"
    assert resolved["status"] == "resolved"
    assert resolved["labels"]["alertname"] == "SentryIssue"
    assert resolved["labels"]["sentry_resource"] == "issue"


def test_normalize_sentry_metric_alert_resolved():
    alert = normalize_sentry(
        sentry_metric_alert_payload(action="resolved"),
        headers={"Sentry-Hook-Resource": "metric_alert"},
    )[0]

    assert alert["source"] == "sentry"
    assert alert["status"] == "resolved"
    assert alert["severity"] == "info"
    assert alert["dedup_key"] == "sentry:metric:metric-alert-7"
    assert alert["external_id"] == "metric-alert-7"
    assert alert["title"] == "High error rate"
    assert alert["labels"]["alertname"] == "SentryMetricAlert"
    assert alert["labels"]["project_slug"] == "backend-api"
    assert alert["labels"]["sentry_alert_id"] == "metric-alert-7"


def test_sentry_endpoint_rejects_missing_route(client, db):
    response = client.post(
        "/api/integrations/sentry/999999",
        data=sentry_body(sentry_issue_alert_payload()),
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "route_not_found"


def test_sentry_endpoint_rejects_non_sentry_route(client, db):
    secret = "sentry-secret"
    group = create_group(slug=unique("infra"))
    team = create_team(group, slug=unique("sre"))
    route = create_route(team, source="alertmanager")

    raw_body = sentry_body(sentry_issue_alert_payload())

    response = client.post(
        f"/api/integrations/sentry/{route.id}",
        data=raw_body,
        content_type="application/json",
        headers={
            "Sentry-Hook-Signature": sentry_signature(secret, raw_body),
            "Sentry-Hook-Resource": "event_alert",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"


def test_sentry_endpoint_rejects_missing_secret(client, db):
    group = create_group(slug=unique("infra"))
    team = create_team(group, slug=unique("sre"))
    route = create_route(team, source="sentry")

    raw_body = sentry_body(sentry_issue_alert_payload())

    response = client.post(
        f"/api/integrations/sentry/{route.id}",
        data=raw_body,
        content_type="application/json",
        headers={
            "Sentry-Hook-Signature": sentry_signature("sentry-secret", raw_body),
            "Sentry-Hook-Resource": "event_alert",
        },
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "sentry_secret_not_configured"


def test_sentry_endpoint_rejects_missing_signature(client, db):
    group = create_group(slug=unique("infra"))
    team = create_team(group, slug=unique("sre"))
    route = create_route(
        team,
        source="sentry",
        integration_config={
            "sentry": {
                "webhook_secret": "sentry-secret",
            },
        },
    )

    response = client.post(
        f"/api/integrations/sentry/{route.id}",
        data=sentry_body(sentry_issue_alert_payload()),
        content_type="application/json",
        headers={
            "Sentry-Hook-Resource": "event_alert",
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "sentry_signature_missing"


def test_sentry_endpoint_rejects_invalid_signature(client, db):
    group = create_group(slug=unique("infra"))
    team = create_team(group, slug=unique("sre"))
    route = create_route(
        team,
        source="sentry",
        integration_config={
            "sentry": {
                "webhook_secret": "sentry-secret",
            },
        },
    )

    raw_body = sentry_body(sentry_issue_alert_payload())

    response = client.post(
        f"/api/integrations/sentry/{route.id}",
        data=raw_body,
        content_type="application/json",
        headers={
            "Sentry-Hook-Signature": sentry_signature("wrong-secret", raw_body),
            "Sentry-Hook-Resource": "event_alert",
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "sentry_signature_invalid"


def test_sentry_endpoint_accepts_valid_signature_without_incidentrelay_token(
    client,
    monkeypatch,
    db,
):
    secret = "sentry-secret"
    group = create_group(slug=unique("infra"))
    team = create_team(group, slug=unique("sre"))
    route = create_route(
        team,
        source="sentry",
        integration_config={
            "sentry": {
                "webhook_secret": secret,
            },
        },
    )

    calls = []

    def fake_process_incoming_alerts(alerts):
        calls.append(alerts)
        return {"ok": True, "count": len(alerts)}, 200

    monkeypatch.setattr(
        "app.views.integrations_view.process_incoming_alerts",
        fake_process_incoming_alerts,
    )

    raw_body = sentry_body(sentry_issue_alert_payload())

    response = client.post(
        f"/api/integrations/sentry/{route.id}",
        data=raw_body,
        content_type="application/json",
        headers={
            "Sentry-Hook-Signature": sentry_signature(secret, raw_body),
            "Sentry-Hook-Resource": "event_alert",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "count": 1}

    assert len(calls) == 1
    alert = calls[0][0]

    assert alert["source"] == "sentry"
    assert alert["status"] == "firing"
    assert alert["dedup_key"] == "sentry:issue:12345"
    assert alert["labels"]["project_slug"] == "backend-api"
