from app.services.routing.routing import build_group_key, find_route_for_alert, is_route_active
from app.services.silences import find_active_silence
from tests.factories import create_group, create_route, create_silence, create_team
from app.modules.db import alerts_repo
from app.services.alerts.lifecycle import upsert_alert


def test_is_route_active_requires_route_team_and_group_to_be_active(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team)

    assert is_route_active(route)

    team.active = False
    team.save()

    assert not is_route_active(route)


def test_find_route_for_alert_matches_source_and_matchers(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="alertmanager",
        matchers={"labels": {"team": "infra"}},
    )

    alert_data = {
        "source": "alertmanager",
        "team_slug": "sre",
        "title": "DiskFull",
        "labels": {"team": "infra"},
        "dedup_key": "dedup-1",
    }

    assert find_route_for_alert(alert_data) == route


def test_find_route_for_alert_records_routing_error_when_no_route_matches(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(
        team,
        source="alertmanager",
        matchers={"labels": {"team": "infra"}},
    )

    alert_data = {
        "source": "alertmanager",
        "team_slug": "sre",
        "title": "DiskFull",
        "labels": {"team": "database"},
        "dedup_key": "dedup-1",
    }

    assert find_route_for_alert(alert_data) is None
    assert alert_data["routing_error"] == "no enabled route matched alert labels"


def test_build_group_key_uses_route_group_by_labels(db):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        group_by=["alertname", "instance"],
    )

    key = build_group_key(
        route,
        {
            "source": "alertmanager",
            "labels": {
                "alertname": "DiskFull",
                "instance": "host1",
            },
        },
    )

    assert key == (
        f"source=alertmanager|team_id={route.team_id}|"
        f"route_id={route.id}|service_id=|"
        "alertname=DiskFull|instance=host1"
    )


def test_find_active_silence_returns_matching_active_silence(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    silence = create_silence(team, matchers={"labels": {"alertname": "DiskFull"}})

    found = find_active_silence(
        team.id,
        {"labels": {"alertname": "DiskFull"}, "title": "DiskFull"},
    )

    assert found == silence


def test_silenced_alert_creates_silenced_group_without_notification(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")

    create_route(team)

    create_silence(
        team,
        matchers={
            "labels": {
                "alertname": "DiskFull",
            }
        },
    )

    calls = []

    monkeypatch.setattr(
        "app.services.alerts.notification_queue.notify_alert",
        lambda alert_group, event_type="notification": calls.append(event_type) or 1,
    )

    result = upsert_alert(
        {
            "source": "alertmanager",
            "team_slug": "sre",
            "external_id": "external-1",
            "dedup_key": "dedup-1",
            "title": "DiskFull",
            "message": "/var is 95% full",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
                "instance": "host1",
            },
            "payload": {},
            "status": "firing",
        }
    )
    alert_group = result.group
    created = result.created_group

    assert created is True
    assert alert_group.status == "silenced"
    assert alert_group.silenced is True
    assert alert_group.alert_count == 1
    assert alert_group.silenced_count == 1
    assert alert_group.firing_count == 0
    assert alert_group.notification_pending is False
    assert calls == []

    child = alerts_repo.list_alerts_for_group(alert_group.id)[0]

    assert child.status == "silenced"
    assert child.silenced is True
