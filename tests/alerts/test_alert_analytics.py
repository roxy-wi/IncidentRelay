from datetime import datetime, timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import Alert, AlertGroup
from tests.factories import (
    create_group,
    create_route,
    create_service,
    create_team,
    create_user,
    unique,
)


def _analytics_group(
    *,
    team,
    route,
    service,
    alertname,
    status,
    first_seen_at,
    acknowledged_at=None,
    resolved_at=None,
    occurrences=1,
    maintenance_suppressed=False,
):
    group_key = unique("analytics-group")
    group = AlertGroup.create(
        team=team,
        route=route,
        service=service,
        source="pytest",
        group_key_hash=group_key,
        group_key=group_key,
        title=alertname,
        message=alertname + " test",
        severity="critical",
        common_labels={"alertname": alertname, "severity": "critical"},
        label_values={},
        payload_summary={"alertname": alertname},
        status=status,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
        first_seen_at=first_seen_at,
        last_seen_at=resolved_at or acknowledged_at or first_seen_at,
        alert_count=occurrences,
        firing_count=occurrences if status == "firing" else 0,
        acknowledged_count=occurrences if status == "acknowledged" else 0,
        resolved_count=occurrences if status == "resolved" else 0,
        maintenance_suppressed=maintenance_suppressed,
    )

    for index in range(occurrences):
        alert_seen_at = first_seen_at + timedelta(minutes=index)
        Alert.create(
            team=team,
            route=route,
            service=service,
            group=group,
            source="pytest",
            external_id=unique("analytics-external"),
            dedup_key=unique("analytics-dedup"),
            group_key=group_key,
            title=alertname,
            message=alertname + " child",
            severity="critical",
            labels={"alertname": alertname, "severity": "critical"},
            payload={},
            status="resolved" if status == "resolved" else "firing",
            first_seen_at=alert_seen_at,
            last_seen_at=resolved_at or acknowledged_at or alert_seen_at,
            resolved_at=resolved_at if status == "resolved" else None,
        )

    return group


def test_alert_analytics_returns_noise_lifecycle_and_attention_metrics(
    client,
    admin_headers,
    db,
):
    now = utc_now().replace(microsecond=0)
    group = create_group()
    team = create_team(group)
    service = create_service(team, name="Billing API")
    route = create_route(team, service=service)

    acknowledged = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="DiskFull",
        status="acknowledged",
        first_seen_at=now - timedelta(hours=4),
        acknowledged_at=now - timedelta(hours=3),
        occurrences=2,
    )
    resolved_without_ack = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="CpuHigh",
        status="resolved",
        first_seen_at=now - timedelta(hours=3),
        resolved_at=now - timedelta(hours=1),
    )
    suppressed = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="MaintenanceNoise",
        status="firing",
        first_seen_at=now - timedelta(hours=2),
        maintenance_suppressed=True,
    )
    stale = _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="ForgottenAlert",
        status="firing",
        first_seen_at=now - timedelta(days=40),
    )

    response = client.get(
        f"/api/alert-groups/analytics?team_id={team.id}&days=7&limit=10",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()

    assert payload["version"] == 1
    assert payload["window"]["days"] == 7

    summary = payload["summary"]
    assert summary["alert_groups"] == 3
    assert summary["occurrences"] == 4
    assert summary["open_now"] == 3
    assert summary["unacknowledged"] == 1
    assert summary["ack_rate"] == 0.5
    assert summary["resolved_without_ack"] == 1
    assert summary["mtta_seconds_p50"] == 3600
    assert summary["mtta_seconds_p95"] == 3600
    assert summary["mttr_seconds_p50"] == 7200
    assert summary["mttr_seconds_p95"] == 7200

    top_noisy = payload["top_noisy"][0]
    assert top_noisy["alertname"] == "DiskFull"
    assert top_noisy["occurrences"] == 2
    assert top_noisy["groups"] == 1
    assert top_noisy["dedup_ratio"] == 2
    assert top_noisy["open"] == 1
    assert top_noisy["ack_rate"] == 1.0

    assert payload["oldest_unresolved"][0]["id"] == stale.id
    assert suppressed.id not in {
        row["id"]
        for row in payload["oldest_unresolved"]
    }

    assert [
        row["id"]
        for row in payload["attention"]["unacknowledged"]
    ] == [stale.id]
    assert [
        row["id"]
        for row in payload["attention"]["resolved_without_ack"]
    ] == [resolved_without_ack.id]

    resolved_health = payload["attention"]["resolved_without_ack_by_alert"]
    assert resolved_health == [{
        "alertname": "CpuHigh",
        "resolved_groups": 1,
        "resolved_without_ack": 1,
        "rate": 1.0,
        "median_lifetime_seconds": 7200,
    }]

    lifecycle = payload["series"]["lifecycle_by_day"]
    assert sum(row["created"] for row in lifecycle) == 3
    assert sum(row["acknowledged"] for row in lifecycle) == 1
    assert sum(row["resolved"] for row in lifecycle) == 1

    assert acknowledged.id != stale.id


def test_alert_analytics_aggregates_resolved_without_ack_by_alertname(
    client,
    admin_headers,
    db,
):
    now = utc_now().replace(microsecond=0)
    group = create_group()
    team = create_team(group)
    service = create_service(team, name="Payments API")
    route = create_route(team, service=service)

    _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="QueueBacklog",
        status="resolved",
        first_seen_at=now - timedelta(hours=4),
        resolved_at=now - timedelta(hours=2),
    )
    _analytics_group(
        team=team,
        route=route,
        service=service,
        alertname="QueueBacklog",
        status="resolved",
        first_seen_at=now - timedelta(hours=3),
        acknowledged_at=now - timedelta(hours=2, minutes=30),
        resolved_at=now - timedelta(hours=1),
    )

    response = client.get(
        f"/api/alert-groups/analytics?team_id={team.id}&days=7&limit=10",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()
    rows = response.get_json()["attention"]["resolved_without_ack_by_alert"]

    assert rows == [{
        "alertname": "QueueBacklog",
        "resolved_groups": 2,
        "resolved_without_ack": 1,
        "rate": 0.5,
        "median_lifetime_seconds": 7200,
    }]


def test_alert_analytics_rejects_invalid_window(client, admin_headers, db):
    response = client.get(
        "/api/alert-groups/analytics?days=366",
        headers=admin_headers,
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_error"
    assert any(detail.get("field") == "days" for detail in payload.get("details", []))


@pytest.fixture
def analytics_dataset(db, monkeypatch):
    """Freeze one clock for adjacent windows and exact drill-down assertions."""
    now = datetime(2026, 11, 10, 12)
    monkeypatch.setattr("app.services.alerts.analytics.utc_now", lambda: now)
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team, service=service)

    def add(name, when, **kwargs):
        return _analytics_group(
            team=team,
            route=route,
            service=service,
            alertname=name,
            first_seen_at=when,
            status=kwargs.pop("status", "firing"),
            **kwargs,
        )

    return now, group, team, add


def selection(client, headers, window, metric="alert_groups", **filters):
    return client.get(
        "/api/alert-groups/analytics/selection",
        headers=headers,
        query_string={
            "since": window["since"],
            "until": window["until"],
            "metric": metric,
            **filters,
        },
    )


def test_comparison_uses_adjacent_half_open_windows_and_response_cutoffs(
    client,
    admin_headers,
    analytics_dataset,
):
    now, _, team, add = analytics_dataset
    current_start = now - timedelta(days=7)
    previous_start = now - timedelta(days=14)
    add("BoundaryPrevious", previous_start, acknowledged_at=previous_start + timedelta(minutes=10))
    late_ack = add(
        "LateAck",
        current_start - timedelta(hours=1),
        acknowledged_at=current_start + timedelta(minutes=5),
    )
    current = add(
        "BoundaryCurrent", current_start, acknowledged_at=current_start + timedelta(minutes=5)
    )
    add("ExcludedEnd", now)
    add("ExcludedBefore", previous_start - timedelta(seconds=1))
    payload = client.get(
        "/api/alert-groups/analytics",
        headers=admin_headers,
        query_string={"team_id": team.id, "days": 7},
    ).get_json()
    comparison = payload["comparison"]
    assert payload["summary"]["alert_groups"] == 1
    assert comparison["previous"]["alert_groups"] == 2
    assert comparison["previous"]["occurrences"] == 2
    assert comparison["previous"]["mtta_samples"] == 1
    assert comparison["previous"]["mtta_seconds_p50"] == 600
    assert comparison["current"]["mtta_seconds_p50"] == 300
    assert comparison["deltas"]["alert_groups"] == {"absolute": -1, "percent": -50.0}
    assert comparison["previous_window"]["until"] == payload["window"]["since"]
    response = selection(client, admin_headers, payload["window"], team_id=team.id)
    assert [row["id"] for row in response.get_json()["items"]] == [current.id]
    response = selection(
        client, admin_headers, comparison["previous_window"], "mtta", team_id=team.id
    )
    assert late_ack.id not in {row["id"] for row in response.get_json()["items"]}
    assert response.get_json()["pagination"]["total_items"] == 1


def test_noise_growth_exact_child_names_pagination_and_old_parent(
    client,
    admin_headers,
    analytics_dataset,
):
    now, _, team, add = analytics_dataset
    previous = add("Disk", now - timedelta(days=9), occurrences=2)
    current = add("Disk", now - timedelta(days=2), occurrences=5)
    add("DiskOther", now - timedelta(days=1), occurrences=4)
    add("Decreased", now - timedelta(days=10), occurrences=3)
    add("Decreased", now - timedelta(days=1), occurrences=1)
    old = add("Disk", now - timedelta(days=20))
    Alert.update(first_seen_at=now - timedelta(hours=2)).where(Alert.group == old).execute()
    payload = client.get(
        "/api/alert-groups/analytics",
        headers=admin_headers,
        query_string={"team_id": team.id, "days": 7},
    ).get_json()
    growth = {row["alertname"]: row for row in payload["noise_growth"]}
    assert growth["Disk"] == {
        "alertname": "Disk",
        "current": 6,
        "previous": 2,
        "increase": 4,
        "percent": 200.0,
    }
    assert growth["DiskOther"]["percent"] is None
    assert "Decreased" not in growth
    response = selection(
        client,
        admin_headers,
        payload["window"],
        "occurrences",
        alertname="Disk",
        team_id=team.id,
        page_size=1,
    )
    result = response.get_json()
    assert result["pagination"]["total_items"] == 2
    assert result["items"][0]["id"] == current.id
    assert result["items"][0]["occurrences"] == 5
    response = selection(
        client,
        admin_headers,
        payload["window"],
        "occurrences",
        alertname="Disk",
        team_id=team.id,
        page_size=1,
        page=2,
    )
    assert response.get_json()["items"][0]["id"] == old.id
    response = selection(
        client,
        admin_headers,
        payload["comparison"]["previous_window"],
        "occurrences",
        alertname="Disk",
        team_id=team.id,
    )
    assert [row["id"] for row in response.get_json()["items"]] == [previous.id]


@pytest.mark.parametrize(
    "zone, timestamps, weekday, hour",
    [
        ("Europe/Moscow", [datetime(2026, 11, 9, 22, 30)], 1, 1),
        ("Asia/Kolkata", [datetime(2026, 11, 9, 19)], 1, 0),
        ("America/New_York", [datetime(2026, 11, 1, 5, 30), datetime(2026, 11, 1, 6, 30)], 6, 1),
    ],
)
def test_heatmap_and_selection_agree_across_timezone_and_dst(
    client,
    admin_headers,
    analytics_dataset,
    zone,
    timestamps,
    weekday,
    hour,
):
    _, _, team, add = analytics_dataset
    ids = {add("Timezone", stamp).id for stamp in timestamps}
    payload = client.get(
        "/api/alert-groups/analytics",
        headers=admin_headers,
        query_string={"team_id": team.id, "days": 30, "timezone": zone},
    ).get_json()
    assert len(payload["heatmap"]["cells"]) == 168
    cell = next(
        cell
        for cell in payload["heatmap"]["cells"]
        if cell["weekday"] == weekday and cell["hour"] == hour
    )
    assert cell["count"] == len(ids)
    response = selection(
        client,
        admin_headers,
        payload["window"],
        team_id=team.id,
        timezone=zone,
        weekday=weekday,
        hour=hour,
    )
    assert {row["id"] for row in response.get_json()["items"]} == ids


def test_empty_comparison_and_suppression_samples(client, admin_headers, analytics_dataset):
    now, _, team, add = analytics_dataset
    add(
        "Suppressed",
        now - timedelta(hours=2),
        acknowledged_at=now - timedelta(hours=1),
        maintenance_suppressed=True,
    )
    payload = client.get(
        "/api/alert-groups/analytics", headers=admin_headers, query_string={"team_id": team.id}
    ).get_json()
    assert payload["comparison"]["current"]["mtta_samples"] == 0
    assert payload["comparison"]["previous"]["ack_rate"] is None
    assert payload["comparison"]["deltas"]["alert_groups"] == {"absolute": 1, "percent": None}
    assert payload["comparison"]["deltas"]["mtta_seconds_p50"] == {
        "absolute": None,
        "percent": None,
    }
    assert sum(cell["count"] for cell in payload["heatmap"]["cells"]) == 1
    response = selection(client, admin_headers, payload["window"], "mtta", team_id=team.id)
    assert response.get_json()["pagination"]["total_items"] == 0


def test_selection_and_new_metrics_preserve_team_permissions(client, analytics_dataset):
    from app.login import create_access_token

    now, group, team, add = analytics_dataset
    visible = add("Visible", now - timedelta(days=1))
    other_team = create_team(create_group())
    other_service = create_service(other_team)
    other_route = create_route(other_team, service=other_service)
    _analytics_group(
        team=other_team,
        service=other_service,
        route=other_route,
        alertname="Hidden",
        first_seen_at=now - timedelta(days=1),
        status="firing",
    )
    user = create_user(group=group, group_role="user_admin")
    headers = {"Authorization": "Bearer " + create_access_token(user)[0]}
    payload = client.get("/api/alert-groups/analytics", headers=headers).get_json()
    assert payload["comparison"]["current"]["alert_groups"] == 1
    assert {row["alertname"] for row in payload["noise_growth"]} == {"Visible"}
    response = selection(client, headers, payload["window"])
    assert [row["id"] for row in response.get_json()["items"]] == [visible.id]
    assert selection(client, headers, payload["window"], team_id=other_team.id).status_code == 403


@pytest.mark.parametrize(
    "extra",
    [
        {"timezone": "Invalid/Timezone"},
        {"hour": 24, "weekday": 1},
        {"weekday": 1},
        {"metric": "occurrences", "weekday": 0, "hour": 1},
        {"metric": "alert_groups", "alertname": "Disk"},
        {"until": "2024-01-01T00:00:00Z"},
        {"since": "2020-01-01T00:00:00Z"},
        {"since": "2026-11-01T00:00:00"},
        {"page_size": 101},
    ],
)
def test_invalid_selection_is_rejected(client, admin_headers, extra):
    params = {
        "metric": "alert_groups",
        "since": "2026-11-01T00:00:00Z",
        "until": "2026-11-08T00:00:00Z",
        **extra,
    }
    response = client.get(
        "/api/alert-groups/analytics/selection", headers=admin_headers, query_string=params
    )
    assert response.status_code == 400, response.get_json()


def test_occurrence_selection_preserves_exact_name_and_reports_missing_parent(
    client,
    admin_headers,
    analytics_dataset,
):
    now, _, team, add = analytics_dataset
    name = ' Disk "full" <production> '
    linked = add(name, now - timedelta(hours=2))
    orphan = add(name, now - timedelta(hours=1))
    Alert.update(group=None).where(Alert.group == orphan).execute()
    add(name.strip(), now - timedelta(hours=1))
    payload = client.get(
        "/api/alert-groups/analytics",
        headers=admin_headers,
        query_string={"team_id": team.id, "days": 7},
    ).get_json()
    response = selection(
        client, admin_headers, payload["window"], "occurrences", alertname=name, team_id=team.id
    )
    assert response.status_code == 200, response.get_json()
    assert [row["id"] for row in response.get_json()["items"]] == [linked.id]
    assert response.get_json()["unlinked_occurrences"] == 1


def test_empty_team_scope_returns_no_comparison_or_selection_data(client, analytics_dataset):
    from app.login import create_access_token

    now, _, _, add = analytics_dataset
    add("Not visible", now - timedelta(days=1))
    user = create_user(group=create_group(), group_role="user_admin")
    headers = {"Authorization": "Bearer " + create_access_token(user)[0]}
    response = client.get("/api/alert-groups/analytics", headers=headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["comparison"]["current"]["alert_groups"] == 0
    assert sum(cell["count"] for cell in payload["heatmap"]["cells"]) == 0
    assert payload["noise_growth"] == []
    response = selection(client, headers, payload["window"], "occurrences")
    assert response.get_json()["items"] == []
    assert response.get_json()["unlinked_occurrences"] == 0
