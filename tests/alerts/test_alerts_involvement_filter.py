from app.login import create_access_token
from app.modules.db import alerts_repo
from tests.factories import (
    add_user_to_team,
    create_group,
    create_incident_responder,
    create_incident_stakeholder,
    create_route,
    create_team,
    create_user,
)


def _alert_group(team, title, assignee=None):
    route = create_route(team, source="test")

    return alerts_repo.create_alert_group(
        team=team.id,
        route=route.id,
        source="test",
        group_key=title,
        title=title,
        message=title,
        severity="critical",
        status="firing",
        assignee=assignee.id if assignee else None,
        common_labels={},
        label_values={},
        payload_summary={},
        alert_count=1,
        firing_count=1,
    )


def _ids(page):
    return {group.id for group in page["items"]}


def _page(**kwargs):
    return alerts_repo.paginate_alert_groups(page_size=100, **kwargs)


def _headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _api_ids(response):
    assert response.status_code == 200, response.get_json()
    return {item["id"] for item in response.get_json()["items"]}


def test_involvement_assigned_matches_assignee_only(db):
    team = create_team(create_group())
    me = create_user()
    other = create_user()

    mine = _alert_group(team, "assigned-mine", assignee=me)
    _alert_group(team, "assigned-other", assignee=other)
    _alert_group(team, "unassigned")

    page = _page(involvement="assigned", involvement_user_id=me.id)

    assert _ids(page) == {mine.id}
    assert _ids(page) == _ids(_page(assigned_to_user_id=me.id))


def test_involvement_responder_rules(db):
    team = create_team(create_group())
    me = create_user()

    direct = _alert_group(team, "responder-direct")
    create_incident_responder(direct, target_user=me, status="requested")

    accepted_via_team = _alert_group(team, "responder-accepted-team")
    create_incident_responder(
        accepted_via_team,
        target_type="team",
        target_team=team,
        accepted_by=me,
        status="accepted",
    )

    resolved = _alert_group(team, "responder-resolved")
    create_incident_responder(resolved, target_user=me, status="resolved")

    declined = _alert_group(team, "responder-declined")
    create_incident_responder(declined, target_user=me, status="declined")

    expired = _alert_group(team, "responder-expired")
    create_incident_responder(expired, target_user=me, status="expired")

    unaccepted_team = _alert_group(team, "responder-team-unaccepted")
    create_incident_responder(
        unaccepted_team,
        target_type="team",
        target_team=team,
        status="requested",
    )

    page = _page(involvement="responder", involvement_user_id=me.id)

    assert _ids(page) == {direct.id, accepted_via_team.id, resolved.id}


def test_involvement_stakeholder_requires_active(db):
    team = create_team(create_group())
    me = create_user()

    active = _alert_group(team, "stakeholder-active")
    create_incident_stakeholder(active, me)

    inactive = _alert_group(team, "stakeholder-inactive")
    create_incident_stakeholder(inactive, me, active=False)

    page = _page(involvement="stakeholder", involvement_user_id=me.id)

    assert _ids(page) == {active.id}


def test_involvement_any_is_union_without_duplicates(db):
    team = create_team(create_group())
    me = create_user()

    both = _alert_group(team, "any-both", assignee=me)
    create_incident_stakeholder(both, me)
    create_incident_responder(both, target_user=me, status="accepted")

    responder_only = _alert_group(team, "any-responder")
    create_incident_responder(responder_only, target_user=me)

    _alert_group(team, "any-unrelated")

    page = _page(involvement="any", involvement_user_id=me.id)

    assert _ids(page) == {both.id, responder_only.id}
    assert page["pagination"]["total_items"] == 2
    assert len(page["items"]) == 2


def test_involvement_without_user_returns_empty(db):
    team = create_team(create_group())
    _alert_group(team, "no-user")

    page = _page(involvement="any", involvement_user_id=None)

    assert page["items"] == []
    assert page["pagination"]["total_items"] == 0


def test_api_involvement_and_legacy_alias(client, admin_user, admin_headers):
    team = create_team(create_group())

    mine = _alert_group(team, "api-assigned", assignee=admin_user)
    stakeholder = _alert_group(team, "api-stakeholder")
    create_incident_stakeholder(stakeholder, admin_user)
    _alert_group(team, "api-unrelated")

    assigned = _api_ids(client.get("/api/alerts?involvement=assigned", headers=admin_headers))
    legacy = _api_ids(client.get("/api/alerts?assigned_to_me=true", headers=admin_headers))
    any_ids = _api_ids(client.get("/api/alerts?involvement=any", headers=admin_headers))

    assert assigned == {mine.id}
    assert legacy == assigned
    assert any_ids == {mine.id, stakeholder.id}


def test_api_invalid_involvement_is_rejected(client, admin_headers):
    response = client.get("/api/alerts?involvement=owner", headers=admin_headers)

    assert response.status_code == 400


def test_api_involvement_never_widens_team_scope(client):
    group = create_group()
    readable = create_team(group)
    hidden = create_team(group)
    user = create_user(group=group, group_role="viewer")
    add_user_to_team(readable, user, role="responder")

    visible = _alert_group(readable, "scope-visible")
    create_incident_stakeholder(visible, user)
    invisible = _alert_group(hidden, "scope-hidden")
    create_incident_stakeholder(invisible, user)

    ids = _api_ids(
        client.get("/api/alerts?involvement=stakeholder", headers=_headers(user))
    )

    assert ids == {visible.id}


def test_api_multiple_team_ids(client, admin_headers):
    group = create_group()
    team_a = create_team(group)
    team_b = create_team(group)
    team_c = create_team(group)

    a = _alert_group(team_a, "multi-team-a")
    b = _alert_group(team_b, "multi-team-b")
    _alert_group(team_c, "multi-team-c")

    both = _api_ids(
        client.get(
            f"/api/alerts?team_id={team_a.id}&team_id={team_b.id}",
            headers=admin_headers,
        )
    )
    single = _api_ids(client.get(f"/api/alerts?team_id={team_a.id}", headers=admin_headers))

    assert both == {a.id, b.id}
    assert single == {a.id}


def test_api_multiple_team_ids_rejects_unreadable_team(client):
    group = create_group()
    readable = create_team(group)
    hidden = create_team(group)
    user = create_user(group=group, group_role="viewer")
    add_user_to_team(readable, user, role="responder")

    ok = client.get(f"/api/alerts?team_id={readable.id}", headers=_headers(user))
    denied = client.get(
        f"/api/alerts?team_id={readable.id}&team_id={hidden.id}",
        headers=_headers(user),
    )

    assert ok.status_code == 200
    assert denied.status_code == 403


def test_api_team_id_must_be_positive(client, admin_headers):
    response = client.get("/api/alerts?team_id=0", headers=admin_headers)

    assert response.status_code == 400
