"""Explain labels distinguish technical alert groups from operational incidents."""

import pytest

from app.modules.db import alerts_repo
from app.modules.db.models import AlertExplainStep, AlertGroup, Incident
from app.services.alerts.explain import AlertExplainTrace
from tests.factories import create_alert, create_group, create_route, create_team


def test_new_group_steps_store_alert_group_titles(db):
    route = create_route(create_team(create_group()))
    alert = create_alert(route)
    group = AlertGroup.create(
        team=route.team,
        route=route,
        source=alert.source,
        group_key=alert.group_key,
        group_key_hash="explain-group-titles",
        title=alert.title,
    )
    alert.group = group
    alert.save()
    incident_count = Incident.select().count()
    trace = AlertExplainTrace.start({"source": alert.source})
    trace.group_created(group)
    trace.group_created_for_existing_alert(group, alert)
    trace.group_reused(group)
    trace.finish(outcome="updated")

    steps = list(alerts_repo.list_alert_explain_steps(trace.row))
    group_steps = {row.code: row for row in steps if row.stage == "group"}
    assert {code: row.title for code, row in group_steps.items()} == {
        "group_created": "Alert group created",
        "group_created_for_existing_alert": "Alert group created for existing alert",
        "group_reused": "Existing alert group reused",
    }
    assert all(row.data["group_id"] == group.id for row in group_steps.values())
    assert trace.row.group_id == group.id
    assert Incident.select().count() == incident_count


@pytest.mark.parametrize(
    "stage, code, stored_title, expected_title",
    [
        ("group", "group_created", "Incident group created", "Alert group created"),
        (
            "group", "group_created_for_existing_alert",
            "Incident group created for existing alert",
            "Alert group created for existing alert",
        ),
        (
            "group", "group_reused",
            "Existing incident group reused", "Existing alert group reused",
        ),
        ("group", "group_created", "Alert group created", "Alert group created"),
        ("group", "group_created", "Custom group title", "Custom group title"),
        ("incident", "group_created", "Incident group created", "Incident group created"),
        ("group", "other_step", "Incident group created", "Incident group created"),
    ],
)
def test_explain_api_displays_legacy_group_titles_without_rewriting_history(
    client, admin_headers, stage, code, stored_title, expected_title,
):
    trace = AlertExplainTrace.start({"source": "test"})
    trace.step(stage, code, "success", stored_title, "Recorded message", group_id=42)
    trace.finish(outcome="created")
    stored = alerts_repo.list_alert_explain_steps(trace.row)[-1]

    response = client.get(
        f"/api/alert-groups/explain/{trace.trace_id}", headers=admin_headers,
    )

    assert response.status_code == 200
    step = next(item for item in response.get_json()["steps"] if item["id"] == stored.id)
    assert step["title"] == expected_title
    assert (step["stage"], step["code"], step["status"]) == (stage, code, "success")
    assert step["message"] == "Recorded message"
    assert step["data"] == {"group_id": 42}
    assert AlertExplainStep.get_by_id(stored.id).title == stored_title
