"""Personal alert filters use Incident membership and preserve alert RBAC."""

import pytest

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db import alerts_repo
from app.modules.db.models import Incident, IncidentAlertGroupLink, IncidentResponder
from tests.factories import (
    add_user_to_team,
    create_group,
    create_incident_stakeholder,
    create_route,
    create_service,
    create_team,
    create_user,
)


def alert_group(team, title, *, assignee=None, service=None, status="firing"):
    """Create a technical group independently of an operational Incident."""
    route = create_route(team, service=service)
    return alerts_repo.create_alert_group(
        team=team,
        route=route,
        service=service,
        source="test",
        group_key=title,
        title=title,
        status=status,
        assignee=assignee,
        severity="critical",
        alert_count=1,
        firing_count=int(status == "firing"),
    )


def linked_incident(group, **kwargs):
    """Create an Incident and a non-removed link to a technical group."""
    incident = Incident.create(team=group.team_id, title=group.title, **kwargs)
    IncidentAlertGroupLink.create(incident=incident, alert_group=group)
    return incident


def headers(user):
    return {"Authorization": "Bearer " + create_access_token(user)[0]}


def api_ids(response):
    assert response.status_code == 200, response.get_json()
    return {item["id"] for item in response.get_json()["items"]}


@pytest.mark.parametrize("involvement", ["assigned", "responder", "stakeholder", "any"])
def test_api_involvement_and_service_intersection(
    client, admin_user, admin_headers, involvement
):
    team = create_team(create_group())
    service = create_service(team)
    assigned = alert_group(team, "assigned", assignee=admin_user, service=service)
    responder = alert_group(team, "responder", service=service)
    IncidentResponder.create(
        incident=linked_incident(responder),
        target_type="user",
        target_user=admin_user,
    )
    stakeholder = alert_group(team, "stakeholder", service=service)
    create_incident_stakeholder(linked_incident(stakeholder), admin_user)
    alert_group(team, "unrelated", service=service)
    alert_group(team, "other-service", assignee=admin_user)
    expected = {
        "assigned": {assigned.id},
        "responder": {responder.id},
        "stakeholder": {stakeholder.id},
        "any": {assigned.id, responder.id, stakeholder.id},
    }
    response = client.get(
        f"/api/alert-groups?involvement={involvement}&service_id={service.id}",
        headers=admin_headers,
    )
    assert api_ids(response) == expected[involvement]
    assert response.get_json()["pagination"]["total_items"] == len(
        expected[involvement]
    )


@pytest.mark.parametrize(
    "status,expected",
    [
        ("requested", True),
        ("accepted", True),
        ("resolved", True),
        ("declined", False),
        ("expired", False),
        ("cancelled", False),
    ],
)
def test_responder_status_and_accepted_team_request(db, status, expected):
    team = create_team(create_group())
    user = create_user()
    direct = alert_group(team, "direct")
    via_team = alert_group(team, "via-team")
    pending_team = alert_group(team, "team-only")
    IncidentResponder.create(
        incident=linked_incident(direct),
        target_type="user",
        target_user=user,
        status=status,
    )
    IncidentResponder.create(
        incident=linked_incident(via_team),
        target_type="team",
        target_team=team,
        accepted_by=user,
        status=status,
    )
    IncidentResponder.create(
        incident=linked_incident(pending_team),
        target_type="team",
        target_team=team,
    )
    result = alerts_repo.paginate_alert_groups(
        involvement="responder", involvement_user_id=user.id
    )
    assert {group.id for group in result["items"]} == (
        {direct.id, via_team.id} if expected else set()
    )


def test_removed_links_and_inactive_subscriptions_do_not_count(db):
    team = create_team(create_group())
    user = create_user()
    removed = alert_group(team, "removed")
    incident = linked_incident(removed)
    create_incident_stakeholder(incident, user)
    IncidentResponder.create(incident=incident, target_type="user", target_user=user)
    IncidentAlertGroupLink.update(removed_at=utc_now()).where(
        IncidentAlertGroupLink.incident == incident
    ).execute()
    inactive = alert_group(team, "inactive")
    subscription = create_incident_stakeholder(linked_incident(inactive), user)
    subscription.active = False
    subscription.save()
    historical = alert_group(team, "historical", status="resolved")
    create_incident_stakeholder(
        linked_incident(historical, workflow_status="closed"), user
    )
    result = alerts_repo.paginate_alert_groups(
        involvement="any", involvement_user_id=user.id
    )
    assert [group.id for group in result["items"]] == [historical.id]


def test_union_does_not_duplicate_rows_or_pagination(client, admin_user, admin_headers):
    team = create_team(create_group())
    both = alert_group(team, "both", assignee=admin_user)
    for _ in range(2):
        incident = linked_incident(both)
        create_incident_stakeholder(incident, admin_user)
        IncidentResponder.create(
            incident=incident, target_type="user", target_user=admin_user
        )
    second = alert_group(team, "second", assignee=admin_user)
    response = client.get(
        "/api/alert-groups?involvement=any&page_size=1&sort=id&order=asc",
        headers=admin_headers,
    )
    assert api_ids(response) == {both.id}
    assert response.get_json()["pagination"]["total_items"] == 2
    response = client.get(
        "/api/alert-groups?involvement=any&page_size=1&page=2&sort=id&order=asc",
        headers=admin_headers,
    )
    assert api_ids(response) == {second.id}


def test_legacy_assignment_is_preserved_and_intersects_involvement(
    client, admin_user, admin_headers
):
    team = create_team(create_group())
    mine = alert_group(team, "mine", assignee=admin_user)
    other = alert_group(team, "other")
    create_incident_stakeholder(linked_incident(other), admin_user)
    for query in (
        "assigned_to_me=true",
        "involvement=assigned",
        "assigned_to_me=true&involvement=any",
    ):
        assert api_ids(
            client.get("/api/alert-groups?" + query, headers=admin_headers)
        ) == {mine.id}
    response = client.get(
        "/api/alert-groups?assigned_to_me=true&involvement=stakeholder",
        headers=admin_headers,
    )
    assert api_ids(response) == set()


def test_involvement_never_expands_team_permissions(client):
    group = create_group()
    readable = create_team(group)
    hidden = create_team(group)
    user = create_user(group=group, group_role="viewer")
    add_user_to_team(readable, user, role="responder")
    visible = alert_group(readable, "visible")
    create_incident_stakeholder(linked_incident(visible), user)
    invisible = alert_group(hidden, "hidden", assignee=user)
    create_incident_stakeholder(linked_incident(invisible), user)
    assert api_ids(
        client.get("/api/alert-groups?involvement=any", headers=headers(user))
    ) == {visible.id}
    assert (
        client.get(
            f"/api/alert-groups?involvement=any&team_id={hidden.id}",
            headers=headers(user),
        ).status_code
        == 403
    )


def test_missing_user_does_not_disable_personal_filter(
    client, admin_headers, monkeypatch
):
    team = create_team(create_group())
    alert_group(team, "not-personal")
    monkeypatch.setattr("app.views.alerts_view._request_user", lambda: None)
    for query in ("involvement=any", "assigned_to_me=true"):
        assert (
            api_ids(client.get("/api/alert-groups?" + query, headers=admin_headers))
            == set()
        )


def test_invalid_involvement_is_rejected(client, admin_headers):
    assert (
        client.get(
            "/api/alert-groups?involvement=owner", headers=admin_headers
        ).status_code
        == 400
    )


def test_openapi_documents_personal_filters():
    from app.api.openapi.spec import build_openapi_spec

    params = {
        item["name"]: item
        for item in build_openapi_spec()["paths"]["/api/alert-groups"]["get"][
            "parameters"
        ]
    }
    assert params["involvement"]["schema"]["enum"] == [
        "assigned",
        "responder",
        "stakeholder",
        "any",
    ]
    assert params["assigned_to_me"]["schema"]["type"] == "boolean"
