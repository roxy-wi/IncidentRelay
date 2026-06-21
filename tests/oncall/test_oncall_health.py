from app.services import oncall_health
from tests.factories import (
    attach_channel,
    create_channel,
    create_escalation_policy,
    create_escalation_policy_rule,
    create_group,
    create_route,
    create_rotation,
    create_team,
    create_user,
)


def _issue_codes(issues):
    """Return issue codes for dataclass- and dict-based health issues."""
    result = set()

    for issue in issues:
        if isinstance(issue, dict):
            code = issue.get("code")
        else:
            code = getattr(issue, "code", None)

        if code:
            result.add(code)

    return result


def test_route_with_rotation_has_assignment_target(db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    rotation = create_rotation(team, users=[user])

    channel = create_channel(group, team)
    route = create_route(
        team,
        name="rotation-route",
        rotation=rotation,
    )
    attach_channel(route, channel)

    issues = oncall_health.collect_team_summary_issues(team)
    codes = _issue_codes(issues)

    assert "route_has_no_assignment_target" not in codes
    assert "route_has_no_rotation" not in codes


def test_route_with_escalation_policy_does_not_require_direct_rotation(db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    rotation = create_rotation(team, users=[user])

    policy = create_escalation_policy(
        team,
        name="primary-escalation",
        enabled=True,
    )
    create_escalation_policy_rule(
        policy,
        position=1,
        target_type="rotation",
        rotation=rotation,
        enabled=True,
    )

    channel = create_channel(group, team)
    route = create_route(
        team,
        name="cloud-alertmanager",
        rotation=None,
        escalation_policy=policy,
    )
    attach_channel(route, channel)

    issues = oncall_health.collect_team_summary_issues(team)
    codes = _issue_codes(issues)

    assert "route_has_no_assignment_target" not in codes
    assert "route_has_no_rotation" not in codes


def test_route_with_user_escalation_target_does_not_require_rotation(db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)

    policy = create_escalation_policy(
        team,
        name="user-escalation",
        enabled=True,
    )
    create_escalation_policy_rule(
        policy,
        position=1,
        target_type="user",
        user=user,
        enabled=True,
    )

    channel = create_channel(group, team)
    route = create_route(
        team,
        name="direct-user-route",
        rotation=None,
        escalation_policy=policy,
    )
    attach_channel(route, channel)

    issues = oncall_health.collect_team_summary_issues(team)
    codes = _issue_codes(issues)

    assert "route_has_no_assignment_target" not in codes
    assert "route_has_no_rotation" not in codes


def test_route_without_rotation_or_policy_reports_missing_target(db):
    group = create_group()
    team = create_team(group)

    channel = create_channel(group, team)
    route = create_route(
        team,
        name="unassigned-route",
        rotation=None,
        escalation_policy=None,
    )
    attach_channel(route, channel)

    issues = oncall_health.collect_team_summary_issues(team)
    codes = _issue_codes(issues)

    assert "route_has_no_assignment_target" in codes


def test_rotation_summary_does_not_run_full_health_scan(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    rotation = create_rotation(team, users=[user])

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "get_rotation_health_summary() must not run full diagnostics"
        )

    monkeypatch.setattr(
        oncall_health,
        "check_rotation_health",
        fail_if_called,
    )

    summary = oncall_health.get_rotation_health_summary(rotation)

    assert summary["status"] in {"ok", "warning", "critical", "unknown"}
    assert summary["partial"] is True


def test_team_summary_does_not_run_full_team_health(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    rotation = create_rotation(team, users=[user])

    policy = create_escalation_policy(team, enabled=True)
    create_escalation_policy_rule(
        policy,
        target_type="rotation",
        rotation=rotation,
    )

    channel = create_channel(group, team)
    route = create_route(
        team,
        rotation=None,
        escalation_policy=policy,
    )
    attach_channel(route, channel)

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "get_team_health_summary() must not run full diagnostics"
        )

    monkeypatch.setattr(
        oncall_health,
        "check_team_oncall_health",
        fail_if_called,
    )

    summary = oncall_health.get_team_health_summary(team)

    assert summary["status"] in {"ok", "warning", "critical", "unknown"}
    assert summary["partial"] is True


def test_removed_informational_issues_are_not_returned(db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    rotation = create_rotation(team, users=[user])

    payload = oncall_health.check_rotation_health(rotation)
    codes = _issue_codes(payload.get("issues", []))

    assert "no_upcoming_overrides" not in codes
    assert "rotation_has_no_reminder_interval" not in codes


def test_rotation_summaries_endpoint_returns_requested_rotation(
    client,
    admin_headers,
    db,
):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    rotation = create_rotation(team, users=[user])

    response = client.get(
        (
            "/api/oncall-health/rotations/summaries"
            f"?rotation_id={rotation.id}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    rotation_id = str(rotation.id)

    assert rotation_id in payload["by_id"]
    assert payload["by_id"][rotation_id]["status"] in {
        "ok",
        "warning",
        "critical",
        "unknown",
    }


def test_team_summaries_endpoint_returns_requested_team(
    client,
    admin_headers,
    db,
):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    rotation = create_rotation(team, users=[user])

    policy = create_escalation_policy(team, enabled=True)
    create_escalation_policy_rule(
        policy,
        target_type="rotation",
        rotation=rotation,
    )

    channel = create_channel(group, team)
    route = create_route(
        team,
        rotation=None,
        escalation_policy=policy,
    )
    attach_channel(route, channel)

    response = client.get(
        (
            "/api/oncall-health/teams/summaries"
            f"?team_id={team.id}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    team_id = str(team.id)

    assert team_id in payload["by_id"]
    assert payload["by_id"][team_id]["status"] in {
        "ok",
        "warning",
        "critical",
        "unknown",
    }


def test_team_health_endpoint_returns_404_for_missing_team(
    client,
    admin_headers,
):
    response = client.get(
        "/api/oncall-health/teams/999999",
        headers=admin_headers,
    )

    assert response.status_code == 404


def test_rotation_health_endpoint_returns_404_for_missing_rotation(
    client,
    admin_headers,
):
    response = client.get(
        "/api/oncall-health/rotations/999999",
        headers=admin_headers,
    )

    assert response.status_code == 404
