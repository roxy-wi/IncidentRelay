#!/usr/bin/env python3
"""Generate deterministic demo AlertGroups, child Alerts and Incidents.

Run from the repository root, for example::

    python tools/seed_alert_analytics_demo.py --team-id 1 --days 90 --groups 140 --purge

Only rows marked by the configured demo source are removed by ``--purge``.
First-class demo Incidents are discovered through links to those demo AlertGroups.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from app import create_app
from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db import incidents_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertRoute,
    Incident,
    IncidentAlertGroupLink,
    IncidentEvent,
    Service,
    Team,
)


DEFAULT_SOURCE = "analytics-demo"


@dataclass(frozen=True)
class AlertPattern:
    alertname: str
    weight: int
    occurrences_min: int
    occurrences_max: int
    ack_probability: float
    resolve_probability: float
    stale_probability: float


PATTERNS = (
    AlertPattern("CPUHigh", 24, 3, 9, 0.70, 0.88, 0.06),
    AlertPattern("DiskFull", 18, 2, 6, 0.75, 0.82, 0.10),
    AlertPattern("PodCrashLoop", 20, 4, 10, 0.60, 0.78, 0.08),
    AlertPattern("LatencyHigh", 22, 3, 7, 0.68, 0.86, 0.04),
    AlertPattern("QueueBacklog", 12, 2, 5, 0.58, 0.70, 0.12),
    AlertPattern("ReplicationLag", 10, 1, 4, 0.62, 0.66, 0.16),
    AlertPattern("SSLExpirySoon", 6, 1, 2, 0.50, 0.92, 0.02),
    AlertPattern("NodeNotReady", 14, 2, 5, 0.65, 0.76, 0.09),
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def weighted_pattern() -> AlertPattern:
    return random.choices(
        PATTERNS,
        weights=[pattern.weight for pattern in PATTERNS],
        k=1,
    )[0]


def _load_scope(team_id: int, route_id: int | None, service_id: int | None):
    team = Team.get_or_none(
        (Team.id == team_id)
        & (Team.active == True)  # noqa: E712
        & (Team.deleted == False)  # noqa: E712
    )
    if not team:
        raise SystemExit(f"Team #{team_id} was not found or is inactive")

    route = None
    if route_id:
        route = AlertRoute.get_or_none(AlertRoute.id == route_id)
        if not route:
            raise SystemExit(f"Route #{route_id} was not found")
        if route.team_id != team.id:
            raise SystemExit("Selected route belongs to another team")

    service = None
    if service_id:
        service = Service.get_or_none(
            (Service.id == service_id)
            & (Service.deleted == False)  # noqa: E712
        )
        if not service:
            raise SystemExit(f"Service #{service_id} was not found")
        if service.team_id != team.id:
            raise SystemExit("Selected service belongs to another team")

    return team, route, service


def _status_for_pattern(pattern: AlertPattern):
    if random.random() < pattern.stale_probability:
        return "firing", False

    acknowledged = random.random() < pattern.ack_probability
    resolved = random.random() < pattern.resolve_probability

    if resolved and not acknowledged:
        return "resolved", True
    if resolved:
        return "resolved", False
    if acknowledged:
        return "acknowledged", False
    return "firing", False


def create_demo_group(
    *,
    team,
    route,
    service,
    source,
    first_seen_at,
    pattern,
    force_status=None,
    resolved_without_ack=None,
    maintenance_suppressed=False,
):
    occurrences = random.randint(pattern.occurrences_min, pattern.occurrences_max)
    status, inferred_without_ack = _status_for_pattern(pattern)
    severity = random.choices(
        ("critical", "high", "warning", "info"),
        weights=(18, 32, 38, 12),
        k=1,
    )[0]
    priority_slug = {
        "critical": "p1",
        "high": "p2",
        "warning": "p3",
        "info": "p4",
    }[severity]
    priority_order = {"p1": 1, "p2": 2, "p3": 3, "p4": 4}[priority_slug]

    if force_status:
        status = force_status
    if resolved_without_ack is None:
        resolved_without_ack = inferred_without_ack

    acknowledged_at = None
    resolved_at = None

    if status in {"acknowledged", "resolved"} and not resolved_without_ack:
        acknowledged_at = first_seen_at + timedelta(minutes=random.randint(5, 180))

    if status == "resolved":
        base = acknowledged_at or first_seen_at
        resolved_at = base + timedelta(minutes=random.randint(15, 360))

    if resolved_without_ack:
        status = "resolved"
        acknowledged_at = None
        resolved_at = first_seen_at + timedelta(minutes=random.randint(15, 300))

    last_seen_at = resolved_at or acknowledged_at or (
        first_seen_at + timedelta(minutes=max(occurrences - 1, 0) * 12)
    )
    group_key = unique("analytics-group")

    group = AlertGroup.create(
        team=team,
        route=route,
        service=service,
        source=source,
        group_key_hash=group_key,
        group_key=group_key,
        title=pattern.alertname,
        message=f"{pattern.alertname} demo analytics group",
        severity=severity,
        common_labels={
            "alertname": pattern.alertname,
            "severity": severity,
            "demo": "true",
        },
        label_values={},
        payload_summary={"alertname": pattern.alertname, "demo": True},
        status=status,
        priority_slug=priority_slug,
        priority_order=priority_order,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        alert_count=occurrences,
        firing_count=occurrences if status == "firing" else 0,
        acknowledged_count=occurrences if status == "acknowledged" else 0,
        resolved_count=occurrences if status == "resolved" else 0,
        maintenance_suppressed=maintenance_suppressed,
    )

    for index in range(occurrences):
        seen_at = first_seen_at + timedelta(minutes=index * 12)
        Alert.create(
            team=team,
            route=route,
            service=service,
            group=group,
            source=source,
            external_id=unique("analytics-external"),
            dedup_key=unique("analytics-dedup"),
            group_key=group_key,
            title=pattern.alertname,
            message=f"{pattern.alertname} demo child alert",
            severity=severity,
            priority_slug=priority_slug,
            priority_order=priority_order,
            labels={
                "alertname": pattern.alertname,
                "severity": severity,
                "demo": "true",
            },
            payload={"demo": True},
            status="resolved" if status == "resolved" else "firing",
            first_seen_at=seen_at,
            last_seen_at=resolved_at or acknowledged_at or seen_at,
            resolved_at=resolved_at if status == "resolved" else None,
        )

    return group


def create_demo_incident(group):
    """Create one historical first-class Incident linked to a demo AlertGroup."""
    priority = (
        incidents_repo.get_priority_by_slug(group.priority_slug)
        if getattr(group, "priority_slug", None)
        else None
    ) or incidents_repo.get_default_priority()
    if not priority:
        return None

    declared_at = group.first_seen_at
    monitoring_at = None
    incident_resolved_at = None
    closed_at = None

    if group.status == "resolved":
        workflow_status = random.choice(("resolved", "closed"))
        incident_resolved_at = group.resolved_at or group.last_seen_at
        lifetime_seconds = max(
            15 * 60,
            int((incident_resolved_at - declared_at).total_seconds()),
        )
        investigation_at = declared_at + timedelta(seconds=max(60, int(lifetime_seconds * 0.20)))
        identified_at = declared_at + timedelta(seconds=max(120, int(lifetime_seconds * 0.55)))
        monitoring_at = declared_at + timedelta(seconds=max(180, int(lifetime_seconds * 0.80)))
        if workflow_status == "closed":
            closed_at = incident_resolved_at + timedelta(minutes=random.randint(10, 120))
    else:
        investigation_at = declared_at + timedelta(minutes=random.randint(5, 45))
        identified_at = investigation_at + timedelta(minutes=random.randint(10, 90))
        if group.status == "firing":
            workflow_status = random.choice(("investigating", "identified"))
        else:
            workflow_status = random.choice(("investigating", "identified", "monitoring"))
            if workflow_status == "monitoring":
                monitoring_at = identified_at + timedelta(minutes=random.randint(10, 60))

    if workflow_status == "investigating":
        final_at = investigation_at
    elif workflow_status == "identified":
        final_at = identified_at
    else:
        final_at = closed_at or incident_resolved_at or monitoring_at or identified_at
    incident = Incident.create(
        team=group.team,
        service=group.service,
        priority=priority,
        workflow_status=workflow_status,
        title=f"[analytics-demo] {group.title}",
        description="Generated by tools/seed_alert_analytics_demo.py",
        summary=f"Demo operational incident for AlertGroup #{group.id}",
        root_cause=("Demo dependency saturation" if incident_resolved_at else None),
        resolution_summary=("Demo condition recovered" if incident_resolved_at else None),
        declared_at=declared_at,
        investigation_started_at=investigation_at,
        identified_at=identified_at if workflow_status != "investigating" else None,
        monitoring_at=monitoring_at,
        resolved_at=incident_resolved_at,
        closed_at=closed_at,
        created_at=declared_at,
        updated_at=final_at,
    )
    IncidentAlertGroupLink.create(
        incident=incident,
        alert_group=group,
        relation_type="primary",
        linked_at=declared_at,
    )
    IncidentEvent.create(
        incident=incident,
        event_type="incident_declared",
        data={"status": "declared", "demo": True},
        created_at=declared_at,
    )
    IncidentEvent.create(
        incident=incident,
        event_type="incident_status_changed",
        data={"from": "declared", "to": "investigating", "demo": True},
        created_at=investigation_at,
    )
    if workflow_status in {"identified", "monitoring", "resolved", "closed"}:
        IncidentEvent.create(
            incident=incident,
            event_type="incident_status_changed",
            data={"from": "investigating", "to": "identified", "demo": True},
            created_at=identified_at,
        )
    if monitoring_at:
        IncidentEvent.create(
            incident=incident,
            event_type="incident_status_changed",
            data={"to": "monitoring", "demo": True},
            created_at=monitoring_at,
        )
    if incident_resolved_at:
        IncidentEvent.create(
            incident=incident,
            event_type="incident_status_changed",
            data={"to": "resolved", "demo": True},
            created_at=incident_resolved_at,
        )
    if closed_at:
        IncidentEvent.create(
            incident=incident,
            event_type="incident_status_changed",
            data={"to": "closed", "demo": True},
            created_at=closed_at,
        )

    return incident


def purge_demo(source):
    group_ids = [
        row.id
        for row in AlertGroup.select(AlertGroup.id).where(AlertGroup.source == source)
    ]
    incident_ids = []
    if group_ids:
        incident_ids = [
            row.incident_id
            for row in (
                IncidentAlertGroupLink
                .select(IncidentAlertGroupLink.incident)
                .where(IncidentAlertGroupLink.alert_group.in_(group_ids))
            )
        ]

    if incident_ids:
        IncidentEvent.delete().where(IncidentEvent.incident.in_(incident_ids)).execute()
        IncidentAlertGroupLink.delete().where(
            IncidentAlertGroupLink.incident.in_(incident_ids)
        ).execute()
        Incident.delete().where(Incident.id.in_(incident_ids)).execute()

    if group_ids:
        Alert.delete().where(Alert.group.in_(group_ids)).execute()
        IncidentAlertGroupLink.delete().where(
            IncidentAlertGroupLink.alert_group.in_(group_ids)
        ).execute()
        AlertGroup.delete().where(AlertGroup.id.in_(group_ids)).execute()

    return len(group_ids), len(set(incident_ids))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-id", type=int, required=True)
    parser.add_argument("--route-id", type=int)
    parser.add_argument("--service-id", type=int)
    parser.add_argument("--days", type=int, default=90, choices=range(1, 366))
    parser.add_argument("--groups", type=int, default=140)
    parser.add_argument("--incident-ratio", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--purge-only", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.groups < 1:
        raise SystemExit("--groups must be >= 1")
    if not 0 <= args.incident_ratio <= 1:
        raise SystemExit("--incident-ratio must be between 0 and 1")
    if (args.purge or args.purge_only) and not args.source.startswith(DEFAULT_SOURCE):
        raise SystemExit(
            "Refusing to purge a source outside the analytics-demo namespace"
        )

    random.seed(args.seed)
    app = create_app(log_role="analytics-demo")

    with app.app_context():
        if database_proxy.is_closed():
            database_proxy.connect(reuse_if_open=True)
        try:
            team, route, service = _load_scope(
                args.team_id,
                args.route_id,
                args.service_id,
            )
            now = utc_now().replace(microsecond=0)
            created_groups = []

            with database_proxy.atomic():
                if args.purge or args.purge_only:
                    removed_groups, removed_incidents = purge_demo(args.source)
                    print(
                        f"purged groups={removed_groups} incidents={removed_incidents} "
                        f"source={args.source}"
                    )
                    if args.purge_only:
                        return

                for _ in range(args.groups):
                    first_seen_at = now - timedelta(
                        days=random.randint(0, args.days - 1),
                        minutes=random.randint(0, 1439),
                    )
                    created_groups.append(
                        create_demo_group(
                            team=team,
                            route=route,
                            service=service,
                            source=args.source,
                            first_seen_at=first_seen_at,
                            pattern=weighted_pattern(),
                        )
                    )

                # Force visible examples for the key analytics tables.
                for index, pattern in enumerate((
                    AlertPattern("CPUHigh", 1, 10, 16, 0.8, 0.9, 0),
                    AlertPattern("PodCrashLoop", 1, 12, 18, 0.7, 0.8, 0),
                    AlertPattern("LatencyHigh", 1, 9, 14, 0.75, 0.88, 0),
                )):
                    created_groups.append(
                        create_demo_group(
                            team=team,
                            route=route,
                            service=service,
                            source=args.source,
                            first_seen_at=now - timedelta(days=7 + index, hours=3),
                            pattern=pattern,
                            force_status="acknowledged",
                        )
                    )

                for days_ago in (28, 41, 63, 84):
                    created_groups.append(
                        create_demo_group(
                            team=team,
                            route=route,
                            service=service,
                            source=args.source,
                            first_seen_at=now - timedelta(days=days_ago, hours=2),
                            pattern=AlertPattern(
                                "ReplicationLag", 1, 2, 4, 0.3, 0.1, 1.0
                            ),
                            force_status="firing",
                        )
                    )

                for days_ago in (1, 2, 4, 9, 13):
                    created_groups.append(
                        create_demo_group(
                            team=team,
                            route=route,
                            service=service,
                            source=args.source,
                            first_seen_at=now - timedelta(days=days_ago, hours=1),
                            pattern=AlertPattern(
                                "QueueBacklog", 1, 1, 3, 0.0, 1.0, 0.0
                            ),
                            force_status="resolved",
                            resolved_without_ack=True,
                        )
                    )

                for days_ago in (3, 5, 8):
                    created_groups.append(
                        create_demo_group(
                            team=team,
                            route=route,
                            service=service,
                            source=args.source,
                            first_seen_at=now - timedelta(days=days_ago, hours=4),
                            pattern=AlertPattern(
                                "MaintenanceNoise", 1, 2, 6, 0.0, 0.0, 1.0
                            ),
                            force_status="firing",
                            maintenance_suppressed=True,
                        )
                    )

                incident_candidates = [
                    group
                    for group in created_groups
                    if not group.maintenance_suppressed
                ]
                random.shuffle(incident_candidates)
                incident_count = round(len(incident_candidates) * args.incident_ratio)
                created_incidents = [
                    create_demo_incident(group)
                    for group in incident_candidates[:incident_count]
                ]
                created_incidents = [item for item in created_incidents if item]

            print("Seeded Alert Analytics demo data")
            print(
                f"team_id={team.id} route_id={getattr(route, 'id', None)} "
                f"service_id={getattr(service, 'id', None)}"
            )
            print(
                f"source={args.source} groups={len(created_groups)} "
                f"incidents={len(created_incidents)} days={args.days} seed={args.seed}"
            )
        finally:
            if not database_proxy.is_closed():
                database_proxy.close()


if __name__ == "__main__":
    main()
