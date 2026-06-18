from app.modules.db import alerts_repo
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import create_group, create_route, create_team, create_user


def _route(group_by=None):
    group = create_group()
    team = create_team(group)

    return create_route(
        team,
        source="webhook",
        matchers={},
        group_by=group_by or ["alertname", "severity"],
    )


def _alert(route, alertname, instance, status="firing"):
    return {
        "source": "webhook",
        "forced_route_id": route.id,
        "external_id": f"{alertname}-{instance}",
        "dedup_key": f"{alertname}:{instance}",
        "status": status,
        "title": alertname,
        "message": f"{alertname} on {instance}",
        "severity": "critical",
        "labels": {
            "alertname": alertname,
            "severity": "critical",
            "instance": instance,
        },
        "payload": {
            "source": "test",
            "instance": instance,
        },
    }


def test_alerts_api_lists_alert_groups(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity"])

    group, created = upsert_alert(_alert(route, "DiskFull", "host1"))
    second_group, second_created = upsert_alert(_alert(route, "DiskFull", "host2"))

    response = client.get(
        "/api/alerts?status=firing",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    items = payload["items"]

    assert created is True
    assert second_created is False
    assert second_group.id == group.id

    assert len(items) == 1
    assert items[0]["type"] == "alert_group"
    assert items[0]["id"] == group.id
    assert items[0]["alert_count"] == 2
    assert items[0]["firing_count"] == 2


def test_alerts_api_detail_contains_child_alerts(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity"])

    group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    upsert_alert(_alert(route, "DiskFull", "host2"))

    response = client.get(
        f"/api/alerts/{group.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert payload["type"] == "alert_group"
    assert payload["id"] == group.id
    assert payload["alert_count"] == 2

    child_ids = {item["dedup_key"] for item in payload["alerts"]}

    assert child_ids == {
        "DiskFull:host1",
        "DiskFull:host2",
    }
    assert all(item["type"] == "alert" for item in payload["alerts"])


def test_ack_alert_group_endpoint_does_not_ack_child_alerts(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity"])

    group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    upsert_alert(_alert(route, "DiskFull", "host2"))

    response = client.post(
        f"/api/alerts/{group.id}/ack",
        json={},
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    children = alerts_repo.list_alerts_for_group(group.id)

    assert payload["type"] == "alert_group"
    assert payload["status"] == "acknowledged"
    assert {alert.status for alert in children} == {"firing"}


def test_resolve_alert_group_endpoint_resolves_child_alerts(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity"])

    group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    upsert_alert(_alert(route, "DiskFull", "host2"))

    response = client.post(
        f"/api/alerts/{group.id}/resolve",
        json={},
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    children = alerts_repo.list_alerts_for_group(group.id)

    assert payload["type"] == "alert_group"
    assert payload["status"] == "resolved"
    assert {alert.status for alert in children} == {"resolved"}


def test_merge_alert_groups_endpoint_moves_child_alerts(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity", "instance"])

    target_group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    source_group, _ = upsert_alert(_alert(route, "DiskFull", "host2"))

    response = client.post(
        "/api/alerts/merge",
        json={
            "target_group_id": target_group.id,
            "source_group_ids": [source_group.id],
            "reason": "same incident",
        },
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    source_group = alerts_repo.get_alert_group(source_group.id)
    target_children = alerts_repo.list_alerts_for_group(target_group.id)

    assert payload["type"] == "alert_group"
    assert payload["id"] == target_group.id
    assert payload["alert_count"] == 2

    assert source_group.status == "merged"
    assert source_group.merged_into_id == target_group.id
    assert {alert.dedup_key for alert in target_children} == {
        "DiskFull:host1",
        "DiskFull:host2",
    }


def test_alert_group_events_endpoint_returns_group_and_child_events(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity"])

    group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    child = alerts_repo.list_alerts_for_group(group.id)[0]

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="group_test",
        message="group event",
    )
    alerts_repo.create_alert_event(
        alert_id=child.id,
        group_id=group.id,
        event_type="child_test",
        message="child event",
    )

    response = client.get(
        f"/api/alerts/{group.id}/events",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    event_types = {event["event_type"] for event in payload}

    assert "group_test" in event_types
    assert "child_test" in event_types


def test_alerts_api_filters_alert_groups_assigned_to_me(
    client,
    admin_headers,
    admin_user,
    db,
):
    route = _route(group_by=["alertname", "severity", "instance"])

    my_group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    other_group, _ = upsert_alert(_alert(route, "DiskFull", "host2"))
    unassigned_group, _ = upsert_alert(_alert(route, "DiskFull", "host3"))

    other_user = create_user(username="other-user")

    my_group.assignee = admin_user
    my_group.save(only=[my_group.__class__.assignee])

    other_group.assignee = other_user
    other_group.save(only=[other_group.__class__.assignee])

    response = client.get(
        "/api/alerts?assigned_to_me=1",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    ids = {item["id"] for item in payload["items"]}

    assert ids == {my_group.id}
    assert other_group.id not in ids
    assert unassigned_group.id not in ids
    assert payload["pagination"]["total_items"] == 1
    assert payload["summary"]["total"] == 1


def test_alerts_api_assigned_to_me_filter_combines_with_status(
    client,
    admin_headers,
    admin_user,
    db,
):
    route = _route(group_by=["alertname", "severity", "instance"])

    firing_group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    resolved_group, _ = upsert_alert(_alert(route, "DiskFull", "host2"))

    firing_group.assignee = admin_user
    firing_group.save(only=[firing_group.__class__.assignee])

    resolved_group.assignee = admin_user
    resolved_group.status = "resolved"
    resolved_group.save(
        only=[
            resolved_group.__class__.assignee,
            resolved_group.__class__.status,
        ]
    )

    response = client.get(
        "/api/alerts?assigned_to_me=1&status=firing",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    ids = {item["id"] for item in payload["items"]}

    assert ids == {firing_group.id}
    assert payload["pagination"]["total_items"] == 1
    assert payload["summary"]["firing"] == 1
    assert payload["summary"]["resolved"] == 0


def test_alerts_api_assigned_to_me_false_does_not_filter(
    client,
    admin_headers,
    admin_user,
    db,
):
    route = _route(group_by=["alertname", "severity", "instance"])

    my_group, _ = upsert_alert(_alert(route, "DiskFull", "host1"))
    other_group, _ = upsert_alert(_alert(route, "DiskFull", "host2"))

    other_user = create_user(username="other-user")

    my_group.assignee = admin_user
    my_group.save(only=[my_group.__class__.assignee])

    other_group.assignee = other_user
    other_group.save(only=[other_group.__class__.assignee])

    response = client.get(
        "/api/alerts?assigned_to_me=false",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    ids = {item["id"] for item in payload["items"]}

    assert my_group.id in ids
    assert other_group.id in ids
    assert payload["pagination"]["total_items"] == 2
