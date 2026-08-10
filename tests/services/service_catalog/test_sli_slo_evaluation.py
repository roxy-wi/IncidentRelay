from datetime import datetime, timedelta

from app.modules.db.models import (
    AlertGroup,
    MaintenanceWindow,
    MaintenanceWindowScope,
    ServiceSli,
    ServiceSlo,
    ServiceSloMeasurement,
)
from app.services.service_catalog.sli_slo import (
    STATUS_AT_RISK,
    STATUS_BREACHED,
    STATUS_MET,
    SLI_TYPE_ACK_LATENCY,
    SLI_TYPE_INCIDENT_AVAILABILITY,
    SLI_TYPE_INCIDENT_COUNT,
    SLI_TYPE_RESOLVE_LATENCY,
    evaluate_service_slo,
    validate_slo_for_sli,
)
from tests.factories import create_group, create_service, create_team
from app.modules.common import utc_now


def _alert_group(service, *, first_seen_at, acknowledged_at=None, resolved_at=None, severity="critical", priority_slug="p1", priority_order=1, status="resolved", key="1"):
    return AlertGroup.create(
        team=service.team,
        service=service,
        source="test",
        group_key_hash="sli-slo-" + str(service.id) + "-" + key,
        group_key="sli-slo/" + key,
        title="Test alert " + key,
        severity=severity,
        priority_slug=priority_slug,
        priority_order=priority_order,
        status=status,
        first_seen_at=first_seen_at,
        last_seen_at=resolved_at or first_seen_at,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
    )


def _sli(service, sli_type, **kwargs):
    return ServiceSli.create(
        service=service,
        slug=kwargs.pop("slug", sli_type.replace("_", "-")),
        name=kwargs.pop("name", sli_type),
        sli_type=sli_type,
        source=kwargs.pop("source", "incidentrelay_alert_groups"),
        configuration=kwargs.pop("configuration", {}),
        severity=kwargs.pop("severity", None),
        priority=kwargs.pop("priority", None),
        **kwargs,
    )


def _slo(service, sli, **kwargs):
    return ServiceSlo.create(
        service=service,
        sli=sli,
        name=kwargs.pop("name", "Test SLO"),
        comparison=kwargs.pop("comparison", "percent_good_gte"),
        target_percent_basis_points=kwargs.pop("target_percent_basis_points", 9500),
        threshold_seconds=kwargs.pop("threshold_seconds", 900),
        threshold_count=kwargs.pop("threshold_count", None),
        window_days=kwargs.pop("window_days", 30),
        exclude_maintenance=kwargs.pop("exclude_maintenance", True),
        include_open_alerts=kwargs.pop("include_open_alerts", True),
        **kwargs,
    )


def test_ack_latency_slo_calculates_percent_good_and_persists_measurement():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(service, SLI_TYPE_ACK_LATENCY, severity="critical")
    slo = _slo(service, sli, target_percent_basis_points=5000, threshold_seconds=900)

    _alert_group(
        service,
        key="good",
        first_seen_at=now - timedelta(hours=2),
        acknowledged_at=now - timedelta(hours=2) + timedelta(minutes=5),
        resolved_at=now - timedelta(hours=1),
    )
    _alert_group(
        service,
        key="bad",
        first_seen_at=now - timedelta(hours=3),
        acknowledged_at=now - timedelta(hours=3) + timedelta(minutes=20),
        resolved_at=now - timedelta(hours=2),
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=True)

    assert evaluation["status"] == STATUS_MET
    assert evaluation["good_count"] == 1
    assert evaluation["bad_count"] == 1
    assert evaluation["total_count"] == 2
    assert evaluation["value_basis_points"] == 5000
    assert evaluation["value_percent"] == 50
    assert evaluation["measurement_id"]

    measurement = ServiceSloMeasurement.get_by_id(evaluation["measurement_id"])
    assert measurement.slo_id == slo.id
    assert measurement.status == STATUS_MET
    assert measurement.good_count == 1
    assert measurement.bad_count == 1


def test_ack_latency_slo_marks_breached_when_percent_is_below_target():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(service, SLI_TYPE_ACK_LATENCY, severity="critical")
    slo = _slo(service, sli, target_percent_basis_points=9500, threshold_seconds=900)

    _alert_group(
        service,
        key="bad",
        first_seen_at=now - timedelta(hours=3),
        acknowledged_at=now - timedelta(hours=3) + timedelta(minutes=20),
        resolved_at=now - timedelta(hours=2),
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["status"] == STATUS_BREACHED
    assert evaluation["value_basis_points"] == 0


def test_incident_availability_merges_overlapping_intervals_and_calculates_budget():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(service, SLI_TYPE_INCIDENT_AVAILABILITY, configuration={"priority_scope": ["p1", "p2"]})
    slo = _slo(
        service,
        sli,
        target_percent_basis_points=9990,
        threshold_seconds=None,
        window_days=1,
    )

    _alert_group(
        service,
        key="a",
        first_seen_at=now - timedelta(hours=4),
        resolved_at=now - timedelta(hours=3),
    )
    _alert_group(
        service,
        key="b",
        first_seen_at=now - timedelta(hours=3, minutes=30),
        resolved_at=now - timedelta(hours=2, minutes=30),
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["status"] == STATUS_BREACHED
    assert evaluation["downtime_seconds"] == 5400
    assert evaluation["total_count"] == 86400
    assert evaluation["budget_seconds"] == 86
    assert evaluation["budget_consumed_seconds"] == 5400
    assert evaluation["budget_remaining_seconds"] == -5314




def test_incident_availability_uses_priority_scope_instead_of_severity():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(
        service,
        SLI_TYPE_INCIDENT_AVAILABILITY,
        configuration={"priority_scope": ["p1", "p2"]},
    )
    slo = _slo(
        service,
        sli,
        target_percent_basis_points=9990,
        threshold_seconds=None,
        window_days=1,
    )

    _alert_group(
        service,
        key="p1-warning",
        severity="warning",
        priority_slug="p1",
        priority_order=1,
        first_seen_at=now - timedelta(hours=4),
        resolved_at=now - timedelta(hours=3),
    )
    _alert_group(
        service,
        key="p3-critical",
        severity="critical",
        priority_slug="p3",
        priority_order=3,
        first_seen_at=now - timedelta(hours=2),
        resolved_at=now - timedelta(hours=1),
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["downtime_seconds"] == 3600
    assert evaluation["bad_count"] == 1

def test_incident_count_slo_uses_value_lte_comparison():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(service, SLI_TYPE_INCIDENT_COUNT, configuration={"priority_scope": ["p1", "p2"]})
    slo = _slo(
        service,
        sli,
        comparison="value_lte",
        target_percent_basis_points=None,
        threshold_seconds=None,
        threshold_count=1,
        window_days=30,
    )

    _alert_group(service, key="one", first_seen_at=now - timedelta(hours=2), resolved_at=now - timedelta(hours=1))
    _alert_group(service, key="two", first_seen_at=now - timedelta(hours=3), resolved_at=now - timedelta(hours=2))

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["status"] == STATUS_BREACHED
    assert evaluation["value_count"] == 2
    assert evaluation["threshold_count"] == 1


def test_validate_slo_for_sli_rejects_wrong_shape():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    sli = _sli(service, SLI_TYPE_INCIDENT_COUNT)

    assert validate_slo_for_sli(sli, {
        "comparison": "percent_good_gte",
        "target_percent_basis_points": 9500,
    }) == "Incident count SLOs must use value_lte comparison"

    assert validate_slo_for_sli(sli, {
        "comparison": "value_lte",
    }) == "Incident count SLOs require threshold_count"


def test_resolve_latency_slo_calculates_good_bad_counts():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(service, SLI_TYPE_RESOLVE_LATENCY, severity="critical")
    slo = _slo(service, sli, target_percent_basis_points=5000, threshold_seconds=900)

    _alert_group(
        service,
        key="resolved-good",
        first_seen_at=now - timedelta(hours=4),
        resolved_at=now - timedelta(hours=4) + timedelta(minutes=10),
    )
    _alert_group(
        service,
        key="resolved-bad",
        first_seen_at=now - timedelta(hours=3),
        resolved_at=now - timedelta(hours=3) + timedelta(minutes=20),
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["status"] == STATUS_MET
    assert evaluation["good_count"] == 1
    assert evaluation["bad_count"] == 1
    assert evaluation["total_count"] == 2
    assert evaluation["value_basis_points"] == 5000
    assert evaluation["value_percent"] == 50


def test_ack_latency_pending_open_alert_marks_slo_at_risk():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(service, SLI_TYPE_ACK_LATENCY, severity="critical")
    slo = _slo(
        service,
        sli,
        target_percent_basis_points=9500,
        threshold_seconds=900,
        include_open_alerts=True,
    )

    _alert_group(
        service,
        key="ack-good",
        first_seen_at=now - timedelta(hours=2),
        acknowledged_at=now - timedelta(hours=2) + timedelta(minutes=5),
        resolved_at=now - timedelta(hours=1),
    )
    _alert_group(
        service,
        key="ack-pending",
        first_seen_at=now - timedelta(minutes=5),
        acknowledged_at=None,
        resolved_at=None,
        status="firing",
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["status"] == STATUS_AT_RISK
    assert evaluation["good_count"] == 1
    assert evaluation["bad_count"] == 0
    assert evaluation["pending_count"] == 1
    assert evaluation["total_count"] == 1
    assert evaluation["value_basis_points"] == 10000


def test_incident_availability_subtracts_service_maintenance_window():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(
        service,
        SLI_TYPE_INCIDENT_AVAILABILITY,
        configuration={"priority_scope": ["p1", "p2"]},
    )
    slo = _slo(
        service,
        sli,
        target_percent_basis_points=9990,
        threshold_seconds=None,
        window_days=1,
        exclude_maintenance=True,
    )

    _alert_group(
        service,
        key="maintenance-overlap",
        first_seen_at=now - timedelta(hours=4),
        resolved_at=now - timedelta(hours=3),
    )

    window = MaintenanceWindow.create(
        group=team.group,
        team=team,
        name="Service maintenance",
        description="Maintenance overlaps first half of downtime.",
        starts_at=now - timedelta(hours=4),
        ends_at=now - timedelta(hours=3, minutes=30),
        timezone="UTC",
        behavior="suppress_notifications",
        status="scheduled",
        enabled=True,
    )
    MaintenanceWindowScope.create(
        maintenance_window=window,
        scope_type="service",
        service=service,
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["downtime_seconds"] == 1800
    assert evaluation["bad_count"] == 1
    assert evaluation["good_count"] == 84600
    assert evaluation["total_count"] == 86400
    assert evaluation["details"]["maintenance_excluded"] is True
    assert evaluation["details"]["maintenance_intervals"] == 1
    assert evaluation["details"]["downtime_intervals"] == 1


def test_incident_count_ignores_non_matching_priority_scope():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = utc_now()

    sli = _sli(
        service,
        SLI_TYPE_INCIDENT_COUNT,
        configuration={"priority_scope": ["p1", "p2"]},
    )
    slo = _slo(
        service,
        sli,
        comparison="value_lte",
        target_percent_basis_points=None,
        threshold_seconds=None,
        threshold_count=1,
        window_days=30,
    )

    _alert_group(
        service,
        key="p1-counted",
        priority_slug="p1",
        priority_order=1,
        first_seen_at=now - timedelta(hours=2),
        resolved_at=now - timedelta(hours=1),
    )
    _alert_group(
        service,
        key="p3-ignored",
        priority_slug="p3",
        priority_order=3,
        first_seen_at=now - timedelta(hours=3),
        resolved_at=now - timedelta(hours=2),
    )

    evaluation = evaluate_service_slo(slo, now=now, persist=False)

    assert evaluation["status"] == STATUS_MET
    assert evaluation["value_count"] == 1
    assert evaluation["threshold_count"] == 1
    assert evaluation["good_count"] == 1
    assert evaluation["bad_count"] == 0


def test_persist_measurement_normalizes_offset_window_to_naive_utc(monkeypatch):
    from types import SimpleNamespace
    from app.services.service_catalog import sli_slo as sli_slo_service

    captured = {}
    marker = object()

    def create_measurement(payload):
        captured.update(payload)
        return marker

    monkeypatch.setattr(
        sli_slo_service.services_repo,
        "create_service_slo_measurement",
        create_measurement,
    )

    slo = SimpleNamespace(service_id=11, sli_id=22, id=33)
    evaluation = {
        "window": {
            "since": "2026-08-10T12:00:00+03:00",
            "until": "2026-08-10T13:30:00+03:00",
        },
        "status": STATUS_MET,
    }

    result = sli_slo_service._persist_measurement(slo, evaluation)

    assert result is marker
    assert captured["window_start"] == datetime(2026, 8, 10, 9, 0, 0)
    assert captured["window_end"] == datetime(2026, 8, 10, 10, 30, 0)
