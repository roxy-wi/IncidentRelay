from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.modules.db.models import CalendarFeed
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_team,
    create_user,
    unique,
)


def create_team_with_rotation():
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Cloud OPS")
    user = create_user(unique("alice"), group, email=f"{unique('alice')}@example.com")
    add_user_to_team(team, user)

    start_at = datetime.utcnow() - timedelta(hours=1)

    create_rotation(
        team,
        name="Primary",
        users=[user],
        start_at=start_at,
        duration_seconds=24 * 3600,
    )

    return group, team, user


def feed_token_from_url(feed_url):
    path = urlparse(feed_url).path
    filename = path.rsplit("/", 1)[-1]

    assert filename.endswith(".ics")

    return filename[:-4]


def test_create_calendar_feed_returns_one_time_subscription_url(
    client,
    admin_headers,
    db,
):
    _, team, _ = create_team_with_rotation()

    response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
            "past_days": 3,
            "future_days": 30,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201

    payload = response.get_json()

    assert payload["id"]
    assert payload["team_id"] == team.id
    assert payload["team_name"] == "Cloud OPS"
    assert payload["name"] == "Outlook subscription"
    assert payload["past_days"] == 3
    assert payload["future_days"] == 30
    assert payload["token"]
    assert payload["feed_url"].endswith(".ics")
    assert f"/api/calendar/feeds/{payload['token']}.ics" in payload["feed_url"]

    feed = CalendarFeed.get_by_id(payload["id"])

    assert feed.team.id == team.id
    assert feed.name == "Outlook subscription"
    assert feed.enabled is True
    assert feed.token_hash
    assert feed.token_prefix == payload["token"][:12]


def test_create_calendar_feed_requires_team_id(client, admin_headers, db):
    response = client.post(
        "/api/calendar/feeds",
        json={
            "name": "Missing team",
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "team_id_required"


def test_list_calendar_feeds_does_not_expose_token_or_feed_url(
    client,
    admin_headers,
    db,
):
    _, team, _ = create_team_with_rotation()

    create_response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
        },
        headers=admin_headers,
    )

    assert create_response.status_code == 201

    response = client.get(
        f"/api/calendar/feeds?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    feeds = response.get_json()

    assert len(feeds) == 1
    assert feeds[0]["team_id"] == team.id
    assert feeds[0]["name"] == "Outlook subscription"
    assert "token" not in feeds[0]
    assert "feed_url" not in feeds[0]


def test_export_calendar_feed_returns_ics_and_marks_last_used(
    client,
    admin_headers,
    db,
):
    _, team, _ = create_team_with_rotation()

    create_response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
        },
        headers=admin_headers,
    )

    assert create_response.status_code == 201

    payload = create_response.get_json()
    token = payload["token"]
    feed_id = payload["id"]

    feed = CalendarFeed.get_by_id(feed_id)
    assert feed.last_used_at is None

    response = client.get(f"/api/calendar/feeds/{token}.ics")

    assert response.status_code == 200
    assert response.mimetype == "text/calendar"
    assert response.headers["Cache-Control"] == "no-store"
    assert "incidentrelay-team" in response.headers["Content-Disposition"]

    body = response.data.decode("utf-8")

    assert "BEGIN:VCALENDAR" in body
    assert "END:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body
    assert "SUMMARY:On-call:" in body
    assert "X-WR-CALNAME:" in body

    feed = CalendarFeed.get_by_id(feed_id)
    assert feed.last_used_at is not None


def test_export_calendar_feed_with_invalid_token_returns_404(client, db):
    response = client.get("/api/calendar/feeds/not-a-real-token.ics")

    assert response.status_code == 404
    assert response.mimetype == "text/plain"


def test_regenerate_calendar_feed_token_invalidates_old_url(
    client,
    admin_headers,
    db,
):
    _, team, _ = create_team_with_rotation()

    create_response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
        },
        headers=admin_headers,
    )

    assert create_response.status_code == 201

    created = create_response.get_json()
    old_token = created["token"]

    assert client.get(f"/api/calendar/feeds/{old_token}.ics").status_code == 200

    regenerate_response = client.post(
        f"/api/calendar/feeds/{created['id']}/token",
        json={},
        headers=admin_headers,
    )

    assert regenerate_response.status_code == 200

    regenerated = regenerate_response.get_json()
    new_token = regenerated["token"]

    assert new_token
    assert new_token != old_token
    assert regenerated["feed_url"].endswith(f"/{new_token}.ics")

    assert client.get(f"/api/calendar/feeds/{old_token}.ics").status_code == 404
    assert client.get(f"/api/calendar/feeds/{new_token}.ics").status_code == 200


def test_regenerate_missing_calendar_feed_returns_404(
    client,
    admin_headers,
    db,
):
    response = client.post(
        "/api/calendar/feeds/999999/token",
        json={},
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "calendar_feed_not_found"


def test_delete_calendar_feed_invalidates_subscription_url(
    client,
    admin_headers,
    db,
):
    _, team, _ = create_team_with_rotation()

    create_response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
        },
        headers=admin_headers,
    )

    assert create_response.status_code == 201

    payload = create_response.get_json()
    token = payload["token"]

    assert client.get(f"/api/calendar/feeds/{token}.ics").status_code == 200

    delete_response = client.delete(
        f"/api/calendar/feeds/{payload['id']}",
        headers=admin_headers,
    )

    assert delete_response.status_code == 200
    assert delete_response.get_json()["deleted"] is True

    assert client.get(f"/api/calendar/feeds/{token}.ics").status_code == 404

    feed = CalendarFeed.get_by_id(payload["id"])
    assert feed.deleted is True
    assert feed.enabled is False


def test_delete_missing_calendar_feed_returns_404(
    client,
    admin_headers,
    db,
):
    response = client.delete(
        "/api/calendar/feeds/999999",
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "calendar_feed_not_found"


def test_calendar_feed_for_inactive_team_returns_403(
    client,
    admin_headers,
    db,
):
    _, team, _ = create_team_with_rotation()

    create_response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
        },
        headers=admin_headers,
    )

    assert create_response.status_code == 201

    token = create_response.get_json()["token"]

    team.active = False
    team.save()

    response = client.get(f"/api/calendar/feeds/{token}.ics")

    assert response.status_code == 403
    assert response.mimetype == "text/plain"


def test_calendar_feed_for_inactive_group_returns_403(
    client,
    admin_headers,
    db,
):
    group, team, _ = create_team_with_rotation()

    create_response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
        },
        headers=admin_headers,
    )

    assert create_response.status_code == 201

    token = create_response.get_json()["token"]

    group.active = False
    group.save()

    response = client.get(f"/api/calendar/feeds/{token}.ics")

    assert response.status_code == 403
    assert response.mimetype == "text/plain"


def test_calendar_feed_can_export_empty_calendar(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Empty Team")

    create_response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Empty subscription",
        },
        headers=admin_headers,
    )

    assert create_response.status_code == 201

    token = create_response.get_json()["token"]

    response = client.get(f"/api/calendar/feeds/{token}.ics")

    assert response.status_code == 200

    body = response.data.decode("utf-8")

    assert "BEGIN:VCALENDAR" in body
    assert "END:VCALENDAR" in body
    assert "BEGIN:VEVENT" not in body


def test_calendar_feed_token_is_not_plaintext_in_database(
    client,
    admin_headers,
    db,
):
    _, team, _ = create_team_with_rotation()

    response = client.post(
        "/api/calendar/feeds",
        json={
            "team_id": team.id,
            "name": "Outlook subscription",
        },
        headers=admin_headers,
    )

    assert response.status_code == 201

    payload = response.get_json()
    token = payload["token"]

    feed = CalendarFeed.get_by_id(payload["id"])

    assert feed.token_hash != token
    assert feed.token_prefix == token[:12]
    assert token not in feed.token_hash
