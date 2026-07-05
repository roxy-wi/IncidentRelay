import pytest

from app.modules.db.models import (
    AlertGroupCorrelation,
    ServiceDependency, AlertEvent,
)
from app.services.alerts.correlation import (
    format_correlation_markdown,
    format_correlation_plain,
    refresh_alert_group_correlations,
)
from app.services.serializers.alerts import serialize_alert_group
from tests.factories import (
    create_group,
    create_impact_alert_group,
    create_service,
    create_team,
    unique,
)
from app.services.alerts.actions import acknowledge_alert, resolve_alert


@pytest.fixture(autouse=True)
def cleanup_correlations(db):
    """Keep correlation tests isolated even if the global fixture misses new table."""
    AlertGroupCorrelation.delete().execute()
    yield
    AlertGroupCorrelation.delete().execute()


def create_firing_group(team, service, title, severity="critical", status="firing"):
    return create_impact_alert_group(
        team=team,
        service=service,
        fingerprint=unique(f"correlation-{service.slug}"),
        status=status,
        severity=severity,
        alertname=title,
        summary=title,
    )


def create_dependency(
    *,
    service,
    depends_on_service,
    dependency_type="hard",
    criticality="critical",
    correlation_enabled=True,
    enabled=True,
    deleted=False,
    propagation_delay_seconds=300,
):
    return ServiceDependency.create(
        service=service,
        depends_on_service=depends_on_service,
        dependency_type=dependency_type,
        criticality=criticality,
        correlation_enabled=correlation_enabled,
        propagation_delay_seconds=propagation_delay_seconds,
        enabled=enabled,
        deleted=deleted,
    )


def create_correlation_fixture():
    group = create_group()
    team = create_team(group=group)

    postgres = create_service(
        team=team,
        slug=unique("postgres"),
        name="PostgreSQL",
    )
    auth_api = create_service(
        team=team,
        slug=unique("auth-api"),
        name="Auth API",
    )

    dependency = create_dependency(
        service=auth_api,
        depends_on_service=postgres,
    )

    return {
        "group": group,
        "team": team,
        "postgres": postgres,
        "auth_api": auth_api,
        "dependency": dependency,
    }


def get_saved_correlation(root_group, related_group, relation_type):
    return AlertGroupCorrelation.get(
        (AlertGroupCorrelation.root_group == root_group.id)
        & (AlertGroupCorrelation.related_group == related_group.id)
        & (AlertGroupCorrelation.relation_type == relation_type)
    )


def count_saved_correlations(root_group, related_group, relation_type):
    return (
        AlertGroupCorrelation
        .select()
        .where(
            (AlertGroupCorrelation.root_group == root_group.id)
            & (AlertGroupCorrelation.related_group == related_group.id)
            & (AlertGroupCorrelation.relation_type == relation_type)
        )
        .count()
    )


def count_active_correlations(root_group, related_group, relation_type):
    return (
        AlertGroupCorrelation
        .select()
        .where(
            (AlertGroupCorrelation.root_group == root_group.id)
            & (AlertGroupCorrelation.related_group == related_group.id)
            & (AlertGroupCorrelation.relation_type == relation_type)
            & (AlertGroupCorrelation.active == True)  # noqa: E712
        )
        .count()
    )


def test_downstream_alert_persists_upstream_root_cause_correlation(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refreshed = refresh_alert_group_correlations(auth_group)

    correlation = get_saved_correlation(
        postgres_group,
        auth_group,
        "possible_root_cause",
    )

    assert len(refreshed) == 1
    assert correlation.root_group_id == postgres_group.id
    assert correlation.related_group_id == auth_group.id
    assert correlation.root_service_id == fixture["postgres"].id
    assert correlation.related_service_id == fixture["auth_api"].id
    assert correlation.dependency_id == fixture["dependency"].id
    assert correlation.relation_type == "possible_root_cause"
    assert correlation.direction == "upstream"
    assert correlation.active is True
    assert correlation.depth == 1
    assert correlation.dependency_type == "hard"
    assert correlation.criticality == "critical"
    assert correlation.score >= 60
    assert "depends on" in correlation.reason


def test_upstream_alert_persists_downstream_impact_correlation(db):
    fixture = create_correlation_fixture()

    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )
    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )

    refreshed = refresh_alert_group_correlations(postgres_group)

    correlation = get_saved_correlation(
        postgres_group,
        auth_group,
        "possible_downstream_impact",
    )

    assert len(refreshed) == 1
    assert correlation.root_group_id == postgres_group.id
    assert correlation.related_group_id == auth_group.id
    assert correlation.root_service_id == fixture["postgres"].id
    assert correlation.related_service_id == fixture["auth_api"].id
    assert correlation.dependency_id == fixture["dependency"].id
    assert correlation.relation_type == "possible_downstream_impact"
    assert correlation.direction == "downstream"
    assert correlation.active is True
    assert correlation.depth == 1
    assert correlation.score >= 60


def test_correlation_format_uses_saved_records(db):
    fixture = create_correlation_fixture()

    create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    plain = "\n".join(format_correlation_plain(auth_group))
    markdown = format_correlation_markdown(auth_group)

    assert "Correlation:" in plain
    assert "Role: possible_symptom" in plain
    assert "Possible root cause:" in plain
    assert "PostgreSQL unavailable" in plain
    assert "score=" in plain

    assert markdown is not None
    assert "**Role:** possible_symptom" in markdown
    assert "**Possible root cause:**" in markdown
    assert "PostgreSQL unavailable" in markdown


def test_alert_group_details_include_saved_correlations(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    data = serialize_alert_group(
        auth_group,
        include_details=True,
    )

    assert data["correlations"]["total"] == 1

    item = data["correlations"]["root_candidates"][0]

    assert item["role"] == "possible_symptom"
    assert item["relation_type"] == "possible_root_cause"
    assert item["root_group"]["id"] == postgres_group.id
    assert item["related_group"]["id"] == auth_group.id
    assert item["peer_group"]["id"] == postgres_group.id
    assert item["score"] >= 60


def test_downstream_impact_is_serialized_for_root_group(db):
    fixture = create_correlation_fixture()

    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )
    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )

    refresh_alert_group_correlations(postgres_group)

    data = serialize_alert_group(
        postgres_group,
        include_details=True,
    )

    assert data["correlations"]["total"] == 1

    item = data["correlations"]["downstream_impacts"][0]

    assert item["role"] == "possible_root_cause"
    assert item["relation_type"] == "possible_downstream_impact"
    assert item["root_group"]["id"] == postgres_group.id
    assert item["related_group"]["id"] == auth_group.id
    assert item["peer_group"]["id"] == auth_group.id


def test_correlation_deactivation_writes_timeline_events(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 1

    assert count_group_events(
        postgres_group,
        "correlation_detected",
    ) == 1
    assert count_group_events(
        auth_group,
        "correlation_detected",
    ) == 1

    auth_group.status = "resolved"
    auth_group.save()

    refreshed = refresh_alert_group_correlations(auth_group)

    assert refreshed == []
    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 0

    correlation = get_saved_correlation(
        postgres_group,
        auth_group,
        "possible_root_cause",
    )

    assert correlation.active is False

    postgres_events = list_group_events(
        postgres_group,
        "correlation_deactivated",
    )
    auth_events = list_group_events(
        auth_group,
        "correlation_deactivated",
    )

    assert len(postgres_events) == 1
    assert len(auth_events) == 1

    assert "Correlation deactivated:" in postgres_events[0].message
    assert "PostgreSQL unavailable" in postgres_events[0].message
    assert "Auth API 5xx" in postgres_events[0].message

    assert auth_events[0].message == postgres_events[0].message

    refresh_alert_group_correlations(auth_group)

    assert count_group_events(
        postgres_group,
        "correlation_deactivated",
    ) == 1
    assert count_group_events(
        auth_group,
        "correlation_deactivated",
    ) == 1


def test_correlation_refresh_does_not_create_duplicates(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)
    refresh_alert_group_correlations(auth_group)
    refresh_alert_group_correlations(auth_group)

    assert count_saved_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 1

    correlation = get_saved_correlation(
        postgres_group,
        auth_group,
        "possible_root_cause",
    )

    assert correlation.active is True
    assert correlation.score >= 60


def test_disabled_dependency_is_ignored(db):
    fixture = create_correlation_fixture()
    fixture["dependency"].enabled = False
    fixture["dependency"].save()

    create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refreshed = refresh_alert_group_correlations(auth_group)

    assert refreshed == []
    assert AlertGroupCorrelation.select().count() == 0


def test_correlation_disabled_dependency_is_ignored(db):
    fixture = create_correlation_fixture()
    fixture["dependency"].correlation_enabled = False
    fixture["dependency"].save()

    create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refreshed = refresh_alert_group_correlations(auth_group)

    assert refreshed == []
    assert AlertGroupCorrelation.select().count() == 0


def test_deleted_dependency_is_ignored(db):
    fixture = create_correlation_fixture()
    fixture["dependency"].deleted = True
    fixture["dependency"].save()

    create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refreshed = refresh_alert_group_correlations(auth_group)

    assert refreshed == []
    assert AlertGroupCorrelation.select().count() == 0


def test_resolved_related_group_is_ignored(db):
    fixture = create_correlation_fixture()

    create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
        status="resolved",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refreshed = refresh_alert_group_correlations(auth_group)

    assert refreshed == []
    assert AlertGroupCorrelation.select().count() == 0


def test_correlation_is_limited_to_same_team(db):
    fixture = create_correlation_fixture()

    other_group = create_group()
    other_team = create_team(group=other_group)

    other_postgres = create_service(
        team=other_team,
        slug=unique("postgres"),
        name="Other PostgreSQL",
    )

    create_firing_group(
        other_team,
        other_postgres,
        "Other PostgreSQL unavailable",
    )

    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refreshed = refresh_alert_group_correlations(auth_group)

    assert refreshed == []
    assert AlertGroupCorrelation.select().count() == 0


def test_two_hop_upstream_dependency_chain_is_correlated(db):
    group = create_group()
    team = create_team(group=group)

    database = create_service(
        team=team,
        slug=unique("database"),
        name="Database",
    )
    backend = create_service(
        team=team,
        slug=unique("backend"),
        name="Backend",
    )
    frontend = create_service(
        team=team,
        slug=unique("frontend"),
        name="Frontend",
    )

    create_dependency(
        service=backend,
        depends_on_service=database,
    )
    create_dependency(
        service=frontend,
        depends_on_service=backend,
    )

    database_group = create_firing_group(
        team,
        database,
        "Database unavailable",
    )
    frontend_group = create_firing_group(
        team,
        frontend,
        "Frontend 5xx",
    )

    refresh_alert_group_correlations(frontend_group)

    correlation = get_saved_correlation(
        database_group,
        frontend_group,
        "possible_root_cause",
    )

    assert correlation.active is True
    assert correlation.direction == "upstream"
    assert correlation.depth == 2
    assert correlation.score >= 60


def test_formatters_return_empty_values_without_saved_correlations(db):
    fixture = create_correlation_fixture()

    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    assert format_correlation_plain(auth_group) == []
    assert format_correlation_markdown(auth_group) is None

    data = serialize_alert_group(
        auth_group,
        include_details=True,
    )

    assert data["correlations"] == {
        "root_candidates": [],
        "downstream_impacts": [],
        "total": 0,
    }


def test_alert_group_serializer_includes_correlation_summary_for_list(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    auth_data = serialize_alert_group(
        auth_group,
        include_details=False,
    )

    assert auth_data["correlation_summary"]["has_correlation"] is True
    assert auth_data["correlation_summary"]["total"] == 1
    assert auth_data["correlation_summary"]["root_candidates"] == 1
    assert auth_data["correlation_summary"]["downstream_impacts"] == 0
    assert auth_data["correlation_summary"]["best_score"] >= 60
    assert "possible_symptom" in auth_data["correlation_summary"]["roles"]

    postgres_data = serialize_alert_group(
        postgres_group,
        include_details=False,
    )

    # Correlation was saved from auth_group refresh, so the postgres side
    # should also show that it has downstream impact.
    assert postgres_data["correlation_summary"]["has_correlation"] is True
    assert postgres_data["correlation_summary"]["total"] == 1
    assert postgres_data["correlation_summary"]["root_candidates"] == 0
    assert postgres_data["correlation_summary"]["downstream_impacts"] == 1
    assert "possible_root_cause" in postgres_data["correlation_summary"]["roles"]


def list_group_events(group, event_type):
    return list(
        AlertEvent
        .select()
        .where(
            (AlertEvent.group == group.id)
            & (AlertEvent.event_type == event_type)
        )
        .order_by(AlertEvent.id.asc())
    )


def count_group_events(group, event_type):
    return len(list_group_events(group, event_type))


def test_correlation_detected_writes_timeline_events_for_both_groups(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    postgres_events = list_group_events(
        postgres_group,
        "correlation_detected",
    )
    auth_events = list_group_events(
        auth_group,
        "correlation_detected",
    )

    assert len(postgres_events) == 1
    assert len(auth_events) == 1

    assert "Correlation detected:" in postgres_events[0].message
    assert "PostgreSQL unavailable" in postgres_events[0].message
    assert "Auth API 5xx" in postgres_events[0].message
    assert "possible_root_cause" in postgres_events[0].message
    assert "score=" in postgres_events[0].message

    assert auth_events[0].message == postgres_events[0].message


def test_correlation_refresh_does_not_duplicate_timeline_events(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)
    refresh_alert_group_correlations(auth_group)
    refresh_alert_group_correlations(auth_group)

    assert count_saved_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 1

    assert count_group_events(
        postgres_group,
        "correlation_detected",
    ) == 1
    assert count_group_events(
        auth_group,
        "correlation_detected",
    ) == 1

    assert count_group_events(
        postgres_group,
        "correlation_deactivated",
    ) == 0
    assert count_group_events(
        auth_group,
        "correlation_deactivated",
    ) == 0


def test_inactive_correlation_can_be_detected_again(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    auth_group.status = "resolved"
    auth_group.save()

    refresh_alert_group_correlations(auth_group)

    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 0

    auth_group.status = "firing"
    auth_group.save()

    refresh_alert_group_correlations(auth_group)

    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 1

    assert count_group_events(
        postgres_group,
        "correlation_detected",
    ) == 2
    assert count_group_events(
        auth_group,
        "correlation_detected",
    ) == 2

    assert count_group_events(
        postgres_group,
        "correlation_deactivated",
    ) == 1
    assert count_group_events(
        auth_group,
        "correlation_deactivated",
    ) == 1


def test_manual_resolve_deactivates_saved_correlations(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 1

    resolved_group = resolve_alert(auth_group.id)

    assert resolved_group.status == "resolved"
    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 0

    assert count_group_events(
        postgres_group,
        "correlation_deactivated",
    ) == 1
    assert count_group_events(
        auth_group,
        "correlation_deactivated",
    ) == 1


def test_manual_acknowledge_keeps_saved_correlations_active(db):
    fixture = create_correlation_fixture()

    postgres_group = create_firing_group(
        fixture["team"],
        fixture["postgres"],
        "PostgreSQL unavailable",
    )
    auth_group = create_firing_group(
        fixture["team"],
        fixture["auth_api"],
        "Auth API 5xx",
    )

    refresh_alert_group_correlations(auth_group)

    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 1

    acknowledged_group = acknowledge_alert(auth_group.id)

    assert acknowledged_group.status == "acknowledged"
    assert count_active_correlations(
        postgres_group,
        auth_group,
        "possible_root_cause",
    ) == 1

    assert count_group_events(
        postgres_group,
        "correlation_deactivated",
    ) == 0
    assert count_group_events(
        auth_group,
        "correlation_deactivated",
    ) == 0
