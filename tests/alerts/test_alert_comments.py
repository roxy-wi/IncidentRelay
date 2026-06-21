from app.login import create_access_token
from app.modules.db.models import AlertEvent, AlertGroup
from tests.factories import (
    add_user_to_team,
    create_alert,
    create_group,
    create_route,
    create_team,
    create_user,
    unique,
)


def make_headers(user):
    token, _ = create_access_token(user)
    return {
        "Authorization": f"Bearer {token}",
    }


def create_test_alert_group():
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))
    route = create_route(team=team)

    alert_group = AlertGroup.create(
        team=team,
        route=route,
        service=route.service,
        rotation=route.rotation,
        escalation_policy=route.escalation_policy,
        source=route.source,
        group_key_hash=unique("group-hash"),
        group_key=unique("group-key"),
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        common_labels={
            "alertname": "DiskFull",
            "instance": "host1",
        },
        label_values={},
        payload_summary={},
        status="firing",
        alert_count=1,
        firing_count=1,
    )

    alert = create_alert(route)
    alert.group = alert_group
    alert.save()

    return group, team, route, alert_group, alert


def create_responder_headers(group, team):
    user = create_user(
        username=unique("responder"),
        group=group,
        group_role="editor",
    )
    add_user_to_team(team, user, role="responder")
    return make_headers(user)


def create_viewer_headers(group, team):
    user = create_user(
        username=unique("viewer"),
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, user, role="viewer")
    return make_headers(user)


def test_create_alert_group_comment_returns_201(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "Investigating this incident"},
        headers=headers,
    )

    assert response.status_code == 201
    payload = response.get_json()

    assert payload["group_id"] == alert_group.id
    assert payload["alert_id"] is None
    assert payload["body"] == "Investigating this incident"
    assert payload["user"] is not None


def test_create_alert_group_comment_rejects_empty_body(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "   "},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_viewer_cannot_create_alert_group_comment(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_viewer_headers(group, team)

    response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "test"},
        headers=headers,
    )

    assert response.status_code == 403


def test_list_alert_group_comments(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    create_response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "First comment"},
        headers=headers,
    )

    assert create_response.status_code == 201

    response = client.get(
        f"/api/alerts/{alert_group.id}/comments",
        headers=headers,
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert len(payload) == 1
    assert payload[0]["group_id"] == alert_group.id
    assert payload[0]["body"] == "First comment"


def test_comment_creates_alert_event(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "Added context"},
        headers=headers,
    )

    assert response.status_code == 201

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == alert_group,
            AlertEvent.event_type == "commented",
        )
        .get_or_none()
    )

    assert event is not None
    assert event.message == "Added context"


def test_update_alert_group_comment(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    create_response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "Initial comment"},
        headers=headers,
    )

    assert create_response.status_code == 201
    comment_id = create_response.get_json()["id"]

    response = client.put(
        f"/api/alerts/{alert_group.id}/comments/{comment_id}",
        json={"body": "Updated comment"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.get_json()

    assert payload["id"] == comment_id
    assert payload["body"] == "Updated comment"
    assert payload["edited"] is True


def test_update_alert_group_comment_rejects_empty_body(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    create_response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "Initial comment"},
        headers=headers,
    )

    assert create_response.status_code == 201
    comment_id = create_response.get_json()["id"]

    response = client.put(
        f"/api/alerts/{alert_group.id}/comments/{comment_id}",
        json={"body": "   "},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_delete_alert_group_comment(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    create_response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "Comment to delete"},
        headers=headers,
    )

    assert create_response.status_code == 201
    comment_id = create_response.get_json()["id"]

    response = client.delete(
        f"/api/alerts/{alert_group.id}/comments/{comment_id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True

    list_response = client.get(
        f"/api/alerts/{alert_group.id}/comments",
        headers=headers,
    )

    assert list_response.status_code == 200
    assert list_response.get_json() == []


def test_delete_alert_group_comment_creates_event(client, db):
    group, team, route, alert_group, alert = create_test_alert_group()
    headers = create_responder_headers(group, team)

    create_response = client.post(
        f"/api/alerts/{alert_group.id}/comments",
        json={"body": "Comment to delete"},
        headers=headers,
    )

    comment_id = create_response.get_json()["id"]

    response = client.delete(
        f"/api/alerts/{alert_group.id}/comments/{comment_id}",
        headers=headers,
    )

    assert response.status_code == 200

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == alert_group,
            AlertEvent.event_type == "comment_deleted",
        )
        .get_or_none()
    )

    assert event is not None
