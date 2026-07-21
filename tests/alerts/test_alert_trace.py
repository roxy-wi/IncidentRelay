from datetime import datetime, timedelta

from types import SimpleNamespace

from app.services.alerts.explain import AlertExplainTrace
from app.services.incidents.priority_policies.resolver import (
    PriorityResolution,
)

from app.services.alerts.explain_cleanup import cleanup_alert_explain_traces
from app.modules.db import alerts_repo, tokens_repo
from app.services.integrations.auth import hash_token
from app.services.alerts.lifecycle import upsert_alert
from tests.conftest import admin_headers
from tests.factories import create_group, create_route, create_team, create_user, unique
from app.modules.common import utc_now


def make_alert_payload(route, **overrides):
    labels = {
        "alertname": "DiskFull",
        "severity": "critical",
        "instance": "host1",
    }

    payload = {
        "source": route.source,
        "forced_route_id": route.id,
        "external_id": unique("external"),
        "dedup_key": unique("dedup"),
        "title": "DiskFull",
        "message": "/var is 95% full",
        "severity": "critical",
        "labels": labels,
        "payload": {
            "source": "test",
            "labels": labels,
        },
        "status": "firing",
    }

    payload.update(overrides)

    return payload


def make_unroutable_alert_payload(**overrides):
    labels = {
        "alertname": "DiskFull",
        "severity": "critical",
        "instance": "host1",
    }

    payload = {
        "source": "unroutable",
        "external_id": unique("external"),
        "dedup_key": unique("dedup"),
        "title": "DiskFull",
        "message": "/var is 95% full",
        "severity": "critical",
        "labels": labels,
        "payload": {
            "source": "test",
            "labels": labels,
        },
        "status": "firing",
    }

    payload.update(overrides)

    return payload


def _trace_steps(trace_id):
    trace = alerts_repo.get_alert_explain_trace(trace_id)

    assert trace is not None

    return trace, alerts_repo.list_alert_explain_steps(trace)


def _priority_resolution(
    slug,
    level,
    *,
    source="policy_rule",
    update_mode="raise_only",
    policy_id=10,
    policy_source="service",
    rule_id=20,
):
    priority = SimpleNamespace(
        id=level,
        slug=slug,
        level=level,
    )

    return PriorityResolution(
        priority=priority,
        source=source,
        update_mode=update_mode,
        policy_id=policy_id,
        policy_source=policy_source,
        rule_id=rule_id,
    )


def test_upsert_alert_returns_processing_result_with_trace(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity"],
    )

    result = upsert_alert(make_alert_payload(route))

    assert result.group is not None
    assert result.alert is not None
    assert result.created_group is True
    assert result.outcome == "created"
    assert result.processing_status == "completed"
    assert result.trace_id

    trace, steps = _trace_steps(result.trace_id)

    assert trace.status == "completed"
    assert trace.outcome == "created"
    assert trace.group_id == result.group.id
    assert trace.alert_id == result.alert.id

    codes = [step.code for step in steps]

    assert "priority_resolution" in codes
    assert "priority_application" in codes

    resolution_step = next(
        step
        for step in steps
        if step.code == "priority_resolution"
    )

    assert resolution_step.data["source"] == "severity_mapping"
    assert resolution_step.data["policy_id"] is None
    assert resolution_step.data["priority_slug"] == "p1"

    application_step = next(
        step
        for step in steps
        if step.code == "priority_application"
    )

    assert application_step.data["action"] == "initialized"
    assert application_step.data["priority_slug"] == "p1"

    assert "alert_received" in codes
    assert "route_matched" in codes
    assert "dedup_lookup_completed" in codes
    assert "group_created" in codes
    assert "alert_created" in codes
    assert "alert_processed" in codes


def test_upsert_alert_routing_failure_has_explain_trace(db):
    result = upsert_alert(make_unroutable_alert_payload())

    assert result.group is None
    assert result.alert is None
    assert result.created_group is False
    assert result.outcome == "routing_failed"
    assert result.processing_status == "stopped"
    assert result.reason == "Alert did not match any active route."
    assert result.trace_id

    trace, steps = _trace_steps(result.trace_id)

    assert trace.status == "stopped"
    assert trace.outcome == "routing_failed"
    assert trace.group_id is None
    assert trace.alert_id is None

    codes = [step.code for step in steps]

    assert "alert_received" in codes
    assert "route_not_matched" in codes


def test_alert_group_explain_api_lists_traces(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity"],
    )

    result = upsert_alert(make_alert_payload(route))

    assert result.group is not None
    assert result.trace_id

    response = client.get(
        f"/api/alerts/{result.group.id}/explain",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["trace_id"] == result.trace_id
    assert payload[0]["group_id"] == result.group.id
    assert payload[0]["alert_id"] == result.alert.id
    assert payload[0]["status"] == "completed"
    assert payload[0]["outcome"] == "created"
    assert payload[0]["steps"] == []


def test_alert_explain_api_returns_trace_with_steps(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity"],
    )

    result = upsert_alert(make_alert_payload(route))

    assert result.trace_id

    response = client.get(
        f"/api/alerts/explain/{result.trace_id}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["trace_id"] == result.trace_id
    assert payload["group_id"] == result.group.id
    assert payload["alert_id"] == result.alert.id
    assert payload["status"] == "completed"
    assert payload["outcome"] == "created"

    steps = payload["steps"]
    codes = [step["code"] for step in steps]

    assert "alert_received" in codes
    assert "route_matched" in codes
    assert "dedup_lookup_completed" in codes
    assert "group_created" in codes
    assert "alert_created" in codes
    assert "alert_processed" in codes


def test_alert_explain_api_returns_404_for_missing_trace(client, admin_headers, db):
    response = client.get(
        "/api/alerts/explain/missing-trace-id",
        headers=admin_headers,
    )

    assert response.status_code == 404

    payload = response.get_json()

    assert payload["error"] == "not_found"
    assert payload["message"] == "Alert explain trace not found."


def test_alert_group_explain_api_returns_404_for_missing_group(client, admin_headers, db):
    response = client.get(
        "/api/alerts/999999/explain",
        headers=admin_headers,
    )

    assert response.status_code == 404

    payload = response.get_json()

    assert payload["error"] == "not_found"
    assert payload["message"] == "Alert group not found."


def make_alertmanager_payload(*, alertname="DiskFull", status="firing", labels=None):
    merged_labels = {
        "alertname": alertname,
        "severity": "critical",
        "instance": "host1",
    }

    if labels:
        merged_labels.update(labels)

    return {
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": merged_labels,
                "annotations": {
                    "summary": f"{alertname} summary",
                    "description": f"{alertname} description",
                },
                "fingerprint": f"{alertname}-host1",
            }
        ],
    }


def post_alertmanager(client, payload, headers=None):
    return client.post(
        "/api/integrations/alertmanager",
        json=payload,
        headers=headers or {},
    )


def make_alerts_write_headers(*, user=None, group=None, team=None):
    raw_token = unique("alerts-write-token")

    tokens_repo.create_api_token(
        name=unique("alerts-write-api-token"),
        token_prefix=raw_token[:12],
        token_hash=hash_token(raw_token),
        scopes=["alerts:write"],
        user_id=user.id if user else None,
        group_id=group.id if group else None,
        team_id=team.id if team else None,
    )

    return {
        "Authorization": f"Bearer {raw_token}",
    }


def test_alertmanager_ingest_response_includes_trace_id(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team=team,
        source="alertmanager",
        matchers={},
        group_by=["alertname", "severity"],
    )

    user = create_user(
        username=unique("alerts-writer"),
        group=group,
        is_admin=True,
    )

    headers = make_alerts_write_headers(
        user=user,
        group=group,
        team=team,
    )

    response = post_alertmanager(
        client,
        make_alertmanager_payload(),
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert isinstance(payload, list)
    assert len(payload) == 1

    item = payload[0]

    assert item["created"] is True
    assert item["group_id"] is not None
    assert item["alert_id"] is not None
    assert item["outcome"] == "created"
    assert item["processing_status"] == "completed"
    assert item["trace_id"]

    trace_response = client.get(
        f"/api/alerts/explain/{item['trace_id']}",
        headers=admin_headers,
    )

    assert trace_response.status_code == 200, trace_response.get_json()


def test_alertmanager_ingest_routing_failure_returns_400_with_trace_id(client, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    create_route(
        team=team,
        source="alertmanager",
        matchers={
            "alertname": "DiskFull",
        },
        group_by=["alertname", "severity"],
    )

    user = create_user(
        username=unique("alerts-writer"),
        group=group,
        is_admin=True,
    )

    headers = make_alerts_write_headers(
        user=user,
        group=group,
        team=team,
    )

    response = post_alertmanager(
        client,
        make_alertmanager_payload(
            alertname="UnroutableAlert",
        ),
        headers=headers,
    )

    assert response.status_code == 400, response.get_json()

    payload = response.get_json()

    assert isinstance(payload, list)
    assert len(payload) == 1

    item = payload[0]

    assert item["created"] is False
    assert item["group_id"] is None
    assert item["alert_id"] is None
    assert item["outcome"] == "routing_failed"
    assert item["processing_status"] == "stopped"
    assert item["reason"]
    assert item["routing_error"] == item["reason"]
    assert item["trace_id"]


def test_alertmanager_routing_failure_trace_can_be_read_by_admin(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    create_route(
        team=team,
        source="alertmanager",
        matchers={
            "alertname": "DiskFull",
        },
        group_by=["alertname", "severity"],
    )

    user = create_user(
        username=unique("alerts-writer"),
        group=group,
        is_admin=True,
    )

    headers = make_alerts_write_headers(
        user=user,
        group=group,
        team=team,
    )

    response = post_alertmanager(
        client,
        make_alertmanager_payload(
            alertname="UnroutableAlert",
        ),
        headers=headers,
    )

    assert response.status_code == 400, response.get_json()

    item = response.get_json()[0]

    trace_response = client.get(
        f"/api/alerts/explain/{item['trace_id']}",
        headers=admin_headers,
    )

    assert trace_response.status_code == 200, trace_response.get_json()

    trace = trace_response.get_json()

    assert trace["trace_id"] == item["trace_id"]
    assert trace["group_id"] is None
    assert trace["alert_id"] is None
    assert trace["status"] == "stopped"
    assert trace["outcome"] == "routing_failed"

    codes = [step["code"] for step in trace["steps"]]

    assert "alert_received" in codes
    assert "route_not_matched" in codes


def test_cleanup_alert_explain_traces_deletes_old_traces(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity"],
    )

    old_payload = make_alert_payload(route)
    old_payload["dedup_key"] = unique("old")
    old_payload["external_id"] = unique("old")

    fresh_payload = make_alert_payload(route)
    fresh_payload["dedup_key"] = unique("fresh")
    fresh_payload["external_id"] = unique("fresh")

    old_result = upsert_alert(old_payload)
    fresh_result = upsert_alert(fresh_payload)

    assert old_result.trace_id
    assert fresh_result.trace_id

    old_trace = alerts_repo.get_alert_explain_trace(old_result.trace_id)
    fresh_trace = alerts_repo.get_alert_explain_trace(fresh_result.trace_id)

    old_trace.started_at = utc_now() - timedelta(days=40)
    old_trace.save()

    cleanup_result = cleanup_alert_explain_traces(retention_days=30)

    assert cleanup_result["traces_deleted"] == 1
    assert cleanup_result["steps_deleted"] > 0

    assert alerts_repo.get_alert_explain_trace(old_result.trace_id) is None
    assert alerts_repo.get_alert_explain_trace(fresh_result.trace_id) is not None


def test_cleanup_alert_explain_traces_rejects_invalid_retention(db):
    try:
        cleanup_alert_explain_traces(retention_days=0)
    except ValueError as exc:
        assert str(exc) == "retention_days must be greater than 0"
    else:
        assert False, "cleanup_alert_explain_traces must reject non-positive retention"


def test_priority_resolution_trace_contains_normalized_severity(db):
    trace = AlertExplainTrace.start({
        "source": "test",
        "dedup_key": unique("dedup"),
        "title": "Database unavailable",
        "severity": "FATAL",
        "status": "firing",
        "labels": {},
    })

    resolution = _priority_resolution(
        "p1",
        1,
        update_mode="initial_only",
    )

    trace.priority_resolution_resolved(
        resolution,
        severity="FATAL",
    )

    _, steps = _trace_steps(trace.trace_id)

    step = next(
        item
        for item in steps
        if item.code == "priority_resolution"
    )

    assert step.data["severity"] == "FATAL"
    assert step.data["normalized_severity"] == "critical"
    assert step.data["priority_slug"] == "p1"
    assert step.data["policy_id"] == 10
    assert step.data["policy_source"] == "service"
    assert step.data["rule_id"] == 20
    assert step.data["update_mode"] == "initial_only"


def test_priority_application_trace_explains_initial_only(db):
    trace = AlertExplainTrace.start({
        "source": "test",
        "dedup_key": unique("dedup"),
        "title": "Critical alert",
        "severity": "critical",
        "status": "firing",
        "labels": {},
    })

    group = SimpleNamespace(
        priority_slug="p5",
        priority_order=5,
        priority_set_manually=False,
    )

    resolution = _priority_resolution(
        "p1",
        1,
        update_mode="initial_only",
    )

    trace.priority_applied(
        group,
        resolution,
        previous_priority_slug="p5",
        previous_priority_order=5,
        created_group=False,
    )

    _, steps = _trace_steps(trace.trace_id)

    step = next(
        item
        for item in steps
        if item.code == "priority_application"
    )

    assert step.status == "skipped"
    assert step.data["action"] == "initial_only_skipped"
    assert step.data["incoming_priority_slug"] == "p1"
    assert step.data["previous_priority_slug"] == "p5"
    assert step.data["priority_slug"] == "p5"


def test_priority_application_trace_explains_manual_override(db):
    trace = AlertExplainTrace.start({
        "source": "test",
        "dedup_key": unique("dedup"),
        "title": "Critical alert",
        "severity": "critical",
        "status": "firing",
        "labels": {},
    })

    group = SimpleNamespace(
        priority_slug="p3",
        priority_order=3,
        priority_set_manually=True,
    )

    resolution = _priority_resolution("p1", 1)

    trace.priority_applied(
        group,
        resolution,
        previous_priority_slug="p3",
        previous_priority_order=3,
        created_group=False,
    )

    _, steps = _trace_steps(trace.trace_id)

    step = next(
        item
        for item in steps
        if item.code == "priority_application"
    )

    assert step.status == "skipped"
    assert step.data["action"] == "manual_priority_preserved"
    assert step.data["priority_set_manually"] is True
    assert step.data["incoming_priority_slug"] == "p1"
    assert step.data["priority_slug"] == "p3"


def test_priority_application_trace_explains_less_severe_priority(db):
    trace = AlertExplainTrace.start({
        "source": "test",
        "dedup_key": unique("dedup"),
        "title": "Low priority alert",
        "severity": "low",
        "status": "firing",
        "labels": {},
    })

    group = SimpleNamespace(
        priority_slug="p2",
        priority_order=2,
        priority_set_manually=False,
    )

    resolution = _priority_resolution(
        "p4",
        4,
        update_mode="raise_only",
    )

    trace.priority_applied(
        group,
        resolution,
        previous_priority_slug="p2",
        previous_priority_order=2,
        created_group=False,
    )

    _, steps = _trace_steps(trace.trace_id)

    step = next(
        item
        for item in steps
        if item.code == "priority_application"
    )

    assert step.status == "skipped"
    assert step.data["action"] == "less_severe_skipped"
    assert step.data["incoming_priority_slug"] == "p4"
    assert step.data["previous_priority_slug"] == "p2"
    assert step.data["priority_slug"] == "p2"
