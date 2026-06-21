from app.modules.db import alerts_repo
from tests.factories import create_group, create_route, create_service, create_team


def _create_alert_group(team, route, service, title, status, severity, group_key):
    counters = {
        "firing_count": 0,
        "acknowledged_count": 0,
        "resolved_count": 0,
        "silenced_count": 0,
    }

    if status == "firing":
        counters["firing_count"] = 1
    elif status == "acknowledged":
        counters["acknowledged_count"] = 1
    elif status == "resolved":
        counters["resolved_count"] = 1
    elif status == "silenced":
        counters["silenced_count"] = 1

    return alerts_repo.create_alert_group(
        team=team.id,
        route=route.id,
        service=service.id,
        source="test",
        group_key=group_key,
        title=title,
        message=title,
        severity=severity,
        status=status,
        common_labels={},
        label_values={},
        payload_summary={},
        alert_count=1,
        silenced=status == "silenced",
        **counters,
    )


def test_paginate_alert_groups_filters_by_multiple_statuses_severities_and_services(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="test")

    service_a = create_service(team, name="API", slug="api")
    service_b = create_service(team, name="DB", slug="db")
    service_c = create_service(team, name="Cache", slug="cache")

    keep_a = _create_alert_group(
        team,
        route,
        service_a,
        "critical firing api",
        "firing",
        "critical",
        "multi-filter-a",
    )
    keep_b = _create_alert_group(
        team,
        route,
        service_b,
        "warning ack db",
        "acknowledged",
        "warning",
        "multi-filter-b",
    )

    _create_alert_group(
        team,
        route,
        service_c,
        "critical firing cache",
        "firing",
        "critical",
        "multi-filter-c",
    )
    _create_alert_group(
        team,
        route,
        service_a,
        "low resolved api",
        "resolved",
        "low",
        "multi-filter-d",
    )

    page = alerts_repo.paginate_alert_groups(
        team_id=team.id,
        status=["firing", "acknowledged"],
        severity=["critical", "warning"],
        service_id=[service_a.id, service_b.id],
        sort="id",
        order="asc",
        page_size=25,
    )

    assert [group.id for group in page["items"]] == [keep_a.id, keep_b.id]
    assert page["pagination"]["total_items"] == 2
    assert page["summary"]["firing"] == 1
    assert page["summary"]["acknowledged"] == 1


def test_paginate_alert_groups_accepts_comma_separated_multi_filters(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="test")

    service = create_service(team, name="API", slug="api-comma")

    keep = _create_alert_group(
        team,
        route,
        service,
        "critical firing api",
        "firing",
        "critical",
        "multi-filter-comma-a",
    )

    _create_alert_group(
        team,
        route,
        service,
        "low resolved api",
        "resolved",
        "low",
        "multi-filter-comma-b",
    )

    page = alerts_repo.paginate_alert_groups(
        team_id=team.id,
        status="firing,acknowledged",
        severity="critical,warning",
        service_id=str(service.id),
        sort="id",
        order="asc",
    )

    assert [group.id for group in page["items"]] == [keep.id]
