from app.modules.db import incidents_repo, alerts_repo
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import (
    create_group,
    create_priority_policy,
    create_priority_policy_rule,
    create_route,
    create_service,
    create_team,
    unique,
)
from app.services.incidents.priorities import reset_incident_priority


def make_alert_payload(
    route,
    *,
    dedup_key=None,
    severity="critical",
    status="firing",
    alertname="DiskFull",
):
    labels = {
        "alertname": alertname,
        "severity": severity,
        "instance": "host1",
    }

    return {
        "source": route.source,
        "forced_route_id": route.id,
        "external_id": unique("external"),
        "dedup_key": dedup_key or unique("dedup"),
        "title": alertname,
        "message": f"{alertname}: {severity}",
        "severity": severity,
        "labels": labels,
        "payload": {
            "labels": labels,
        },
        "status": status,
    }


def create_priority_route():
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    service = create_service(team, slug=unique("service"))
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname"],
    )

    route.service = service
    route.save()

    return group, team, service, route


def create_policy(
    team,
    priority_slug,
    *,
    update_mode="raise_only",
    default_for_team=False,
    matchers=None,
):
    policy = create_priority_policy(
        team,
        name=unique("priority-policy"),
    )

    policy.update_mode = update_mode
    policy.source_priority_mode = "ignore"
    policy.fallback_mode = "severity_mapping"
    policy.default_for_team = default_for_team
    policy.enabled = True
    policy.save()

    priority = incidents_repo.get_priority_by_slug(priority_slug)
    rule = create_priority_policy_rule(
        policy,
        priority,
        name=unique("priority-rule"),
    )

    rule.position = 1
    rule.matchers = matchers or {}
    rule.enabled = True
    rule.save()

    return policy


def assign_service_policy(service, policy):
    service.priority_policy = policy
    service.save()


def test_service_priority_policy_overrides_team_default(db):
    _, team, service, route = create_priority_route()

    create_policy(
        team,
        "p2",
        default_for_team=True,
    )

    service_policy = create_policy(
        team,
        "p1",
    )

    assign_service_policy(service, service_policy)

    result = upsert_alert(
        make_alert_payload(
            route,
            severity="info",
        )
    )

    assert result.group.priority_slug == "p1"

    trace = result.trace.row
    steps = alerts_repo.list_alert_explain_steps(trace)

    resolution_step = next(
        step
        for step in steps
        if step.code == "priority_resolution"
    )

    assert resolution_step.data["policy_id"] == service_policy.id
    assert resolution_step.data["policy_source"] == "service"
    assert resolution_step.data["source"] == "policy_rule"


def test_raise_only_never_lowers_incident_priority(db):
    _, team, service, route = create_priority_route()

    policy = create_policy(
        team,
        "p1",
        update_mode="raise_only",
        matchers={"severity": "critical"},
    )

    assign_service_policy(service, policy)

    first = upsert_alert(
        make_alert_payload(
            route,
            severity="critical",
        )
    )

    assert first.group.priority_slug == "p1"

    second = upsert_alert(
        make_alert_payload(
            route,
            severity="info",
        )
    )

    assert second.group.id == first.group.id
    assert second.group.priority_slug == "p1"


def test_recalculate_lowers_priority_to_highest_active_alert(db):
    _, team, service, route = create_priority_route()

    policy = create_policy(
        team,
        "p1",
        update_mode="recalculate",
        matchers={"severity": "critical"},
    )

    assign_service_policy(service, policy)

    critical_dedup_key = unique("critical")

    critical = upsert_alert(
        make_alert_payload(
            route,
            dedup_key=critical_dedup_key,
            severity="critical",
        )
    )

    lower = upsert_alert(
        make_alert_payload(
            route,
            severity="info",
        )
    )

    assert lower.group.id == critical.group.id
    assert lower.group.priority_slug == "p1"

    resolved = upsert_alert(
        make_alert_payload(
            route,
            dedup_key=critical_dedup_key,
            severity="critical",
            status="resolved",
        )
    )

    assert resolved.group.priority_slug == "p5"


def test_initial_only_does_not_update_existing_incident(db):
    _, team, service, route = create_priority_route()

    policy = create_policy(
        team,
        "p1",
        update_mode="initial_only",
        matchers={"severity": "critical"},
    )

    assign_service_policy(service, policy)

    initial = upsert_alert(
        make_alert_payload(
            route,
            severity="info",
        )
    )

    assert initial.group.priority_slug == "p5"

    critical = upsert_alert(
        make_alert_payload(
            route,
            severity="critical",
        )
    )

    assert critical.group.id == initial.group.id
    assert critical.group.priority_slug == "p5"


def test_manual_priority_is_never_overwritten(db):
    _, team, service, route = create_priority_route()

    policy = create_policy(
        team,
        "p1",
        update_mode="recalculate",
        matchers={"severity": "critical"},
    )

    assign_service_policy(service, policy)

    initial = upsert_alert(
        make_alert_payload(
            route,
            severity="info",
        )
    )

    manual_priority = incidents_repo.get_priority_by_slug("p4")
    group = initial.group
    group.priority = manual_priority
    group.priority_slug = manual_priority.slug
    group.priority_order = manual_priority.level
    group.priority_set_manually = True
    group.save()

    result = upsert_alert(
        make_alert_payload(
            route,
            severity="critical",
        )
    )

    assert result.group.priority_slug == "p4"
    assert result.group.priority_set_manually is True


def test_reset_manual_priority_uses_initial_alert_for_initial_only(db):
    _, team, service, route = create_priority_route()
    policy = create_policy(team, "p1", update_mode="initial_only", matchers={"severity": "critical"})
    assign_service_policy(service, policy)

    initial = upsert_alert(make_alert_payload(route, severity="info"))
    upsert_alert(make_alert_payload(route, severity="critical"))
    incidents_repo.set_incident_priority(initial.group.id, "p2", manual=True)

    group = reset_incident_priority(group_id=initial.group.id)

    assert group.priority_slug == "p5"
    assert group.priority_set_manually is False
    assert group.priority_set_by_id is None
    assert group.priority_set_at is None


def test_reset_manual_priority_uses_highest_historical_alert_for_raise_only(db):
    _, team, service, route = create_priority_route()
    policy = create_policy(team, "p1", update_mode="raise_only", matchers={"severity": "critical"})
    assign_service_policy(service, policy)

    info = upsert_alert(make_alert_payload(route, severity="info"))
    critical_dedup_key = unique("critical")
    upsert_alert(make_alert_payload(route, dedup_key=critical_dedup_key, severity="critical"))
    upsert_alert(make_alert_payload(route, dedup_key=critical_dedup_key, severity="critical", status="resolved"))
    incidents_repo.set_incident_priority(info.group.id, "p4", manual=True)

    group = reset_incident_priority(group_id=info.group.id)

    assert group.priority_slug == "p1"
    assert group.priority_set_manually is False


def test_reset_manual_priority_uses_highest_active_alert_for_recalculate(db):
    _, team, service, route = create_priority_route()
    policy = create_policy(team, "p1", update_mode="recalculate", matchers={"severity": "critical"})
    assign_service_policy(service, policy)

    critical_dedup_key = unique("critical")
    critical = upsert_alert(make_alert_payload(route, dedup_key=critical_dedup_key, severity="critical"))
    upsert_alert(make_alert_payload(route, severity="info"))
    incidents_repo.set_incident_priority(critical.group.id, "p2", manual=True)
    upsert_alert(make_alert_payload(route, dedup_key=critical_dedup_key, severity="critical", status="resolved"))

    group = reset_incident_priority(group_id=critical.group.id)

    assert group.priority_slug == "p5"
    assert group.priority_set_manually is False


def test_missing_policy_keeps_legacy_severity_mapping(db):
    _, _, _, route = create_priority_route()

    result = upsert_alert(
        make_alert_payload(
            route,
            severity="critical",
        )
    )

    assert result.alert.priority_slug == "p1"
    assert result.group.priority_slug == "p1"
