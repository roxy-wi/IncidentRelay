"""2.4 operator-facing AlertGroup reopen contracts backed by persisted data."""

import pytest

from app.login import create_access_token
from app.modules.db.models import AlertExplainStep, AlertExplainTrace
from app.services.alerts import lifecycle
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.runtime import RuntimeResult
from tests.factories import (
    add_user_to_team,
    create_group,
    create_route,
    create_team,
    create_user,
    unique,
)


def _signal(route, key, *, status="firing"):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": key,
        "dedup_key": key,
        "title": "DiskFull",
        "message": "Disk full",
        "severity": "critical",
        "status": status,
        "labels": {"alertname": "DiskFull"},
        "payload": {},
    }


def _make_route(monkeypatch, *, reopen_window):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(
            grouping_reopen_window_seconds=reopen_window,
        ),
    )
    return group, team, route


def _policy_step(trace_id):
    trace = AlertExplainTrace.get(AlertExplainTrace.trace_id == trace_id)
    return AlertExplainStep.get(
        (AlertExplainStep.trace == trace.id)
        & (AlertExplainStep.code == "reopen_policy")
    )


@pytest.mark.parametrize("window,enabled", [(0, False), (300, True)])
def test_explain_records_effective_reopen_policy_including_disabled(db, monkeypatch, window, enabled):
    _, _, route = _make_route(monkeypatch, reopen_window=window)
    first = upsert_alert(_signal(route, unique("reopen-explain")))
    policy = _policy_step(first.trace_id)
    assert policy.data["reopen_window_seconds"] == window
    assert policy.data["enabled"] is enabled
    assert policy.data["eligible"] is enabled


def test_alert_group_details_links_reopened_event_to_new_immutable_child(
    client, db, monkeypatch,
):
    group, team, route = _make_route(monkeypatch, reopen_window=300)
    user = create_user(group=group)
    add_user_to_team(team, user, role="viewer")
    token, _ = create_access_token(user)
    headers = {"Authorization": f"Bearer {token}"}

    key = unique("reopen-details")
    first = upsert_alert(_signal(route, key))
    upsert_alert(_signal(route, key, status="resolved"))
    reopened = upsert_alert(_signal(route, key))
    assert reopened.outcome == "reopened"

    response = client.get(f"/api/alert-groups/{first.group.id}", headers=headers)
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    event = next(item for item in payload["events"] if item["event_type"] == "reopened")
    assert event["group_id"] == first.group.id
    assert event["alert_id"] == reopened.alert.id
    assert event["user_id"] is None
    children = {item["id"]: item for item in payload["alerts"]}
    assert children[first.alert.id]["status"] == "resolved"
    assert children[reopened.alert.id]["status"] == "firing"
