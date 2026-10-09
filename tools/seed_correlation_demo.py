#!/usr/bin/env python3
"""Seed reproducible dependency-aware alert correlations for IncidentRelay.

This tool writes *directly to the configured database* without invoking intake,
notifications, escalation or external integrations. It does not migrate tables.

Run from the repository root after applying migrations:

    python tools/seed_correlation_demo.py --team-id 1 --dry-run
    python tools/seed_correlation_demo.py --team-id 1 --yes
    python tools/seed_correlation_demo.py --team-id 1 --with-incident --yes

The GitLab-like entries are *ServiceEvent demo fixtures*, not incoming GitLab
webhooks or established deployment-to-alert causality.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Allow `python tools/seed_correlation_demo.py` from a source checkout.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import database_proxy, init_database  # noqa: E402
from app.modules.common import utc_now  # noqa: E402
from app.modules.db import alerts_repo, models as m  # noqa: E402
from app.services.alerts.correlation import (  # noqa: E402
    refresh_alert_group_correlations,
)


DEMO_SOURCE = "demo_correlation"
DEPLOY_SOURCE = "demo_gitlab"
SCENARIO_VERSION = "v1"
SERVICE_SPECS = (
    ("postgres", "PostgreSQL", "database", "critical", "tier_1"),
    ("redis", "Redis", "cache", "high", "tier_2"),
    ("checkout", "Checkout API", "api", "critical", "tier_1"),
    ("storefront", "Storefront", "web", "high", "tier_2"),
    ("monitoring", "Independent Monitoring", "infrastructure", "medium", "tier_3"),
)
# service depends_on_service, dependency_type, criticality
DEPENDENCIES = (
    ("checkout", "postgres", "hard", "required"),
    ("checkout", "redis", "hard", "required"),
    ("storefront", "checkout", "hard", "required"),
)
# scenario, service, alert name, severity, priority, status, age of first event,
# age of last event, raw occurrences and ACK delay in minutes
ACTIVE_SCENARIOS = (
    ("postgres-root", "postgres", "PostgresConnectionsExhausted", "critical", "p1", "firing", 21, 4, 7, None),
    ("redis-root", "redis", "RedisConnectionsFailed", "critical", "p1", "firing", 20, 4, 5, None),
    ("checkout-symptom", "checkout", "Checkout5xxRateHigh", "high", "p2", "acknowledged", 18, 3, 10, 7),
    ("storefront-symptom", "storefront", "CheckoutButtonFailures", "high", "p2", "firing", 16, 2, 8, None),
    ("isolated", "monitoring", "DiskSpaceLow", "warning", "p3", "firing", 360, 50, 4, None),
)
HISTORY_ALERTS = (
    ("postgres", "PostgresConnectionsExhausted", "critical", "p1"),
    ("checkout", "Checkout5xxRateHigh", "high", "p2"),
    ("storefront", "CheckoutButtonFailures", "warning", "p3"),
    ("redis", "RedisConnectionsFailed", "warning", "p3"),
    ("checkout", "CheckoutLatencyHigh", "high", "p2"),
    ("monitoring", "DiskSpaceLow", "warning", "p3"),
)


def validate_prefix(prefix: str) -> str:
    value = str(prefix or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,28}", value):
        raise ValueError("prefix must match [a-z][a-z0-9_-]{1,28}")
    return value


def _tag(prefix: str, team_id: int) -> str:
    return f"{prefix}:{team_id}:{SCENARIO_VERSION}"


def _check_owner(value, tag, what):
    if not isinstance(value, dict) or value.get("correlation_demo_owner") != tag:
        raise RuntimeError(f"Refusing to modify unowned {what}; choose another --prefix")


def _service(team, prefix, tag, spec):
    suffix, title, kind, criticality, tier = spec
    slug = f"{prefix}-{suffix}"
    service = m.Service.get_or_none(
        (m.Service.team == team.id) & (m.Service.slug == slug)
    )
    if service is not None:
        _check_owner(service.metadata, tag, f"service {slug}")
        if service.deleted:
            raise RuntimeError(f"Owned service {slug} is deleted; restore it manually first")
        if not service.enabled:
            raise RuntimeError(f"Owned service {slug} is disabled; enable it before reseeding")
        return service

    return m.Service.create(
        team=team.id,
        group=team.group_id,
        slug=slug,
        name=f"[Demo] {title}",
        description="Reproducible dependency/alert correlation demo; no live monitoring",
        kind="technical",
        lifecycle="production",
        service_type=kind,
        environment="production",
        criticality=criticality,
        tier=tier,
        status="operational",
        status_source="manual",
        labels={"demo_seed": prefix, "correlation_demo_owner": tag},
        tags=["demo", "correlation"],
        metadata={"correlation_demo_owner": tag},
        enabled=True,
        public=False,
    )


def _dependency(services, prefix, tag, spec):
    dependent, upstream, dep_type, criticality = spec
    service = services[dependent]
    depends_on = services[upstream]
    relation = m.ServiceDependency.get_or_none(
        (m.ServiceDependency.service == service.id)
        & (m.ServiceDependency.depends_on_service == depends_on.id)
    )
    if relation is not None:
        _check_owner(relation.metadata, tag, f"dependency {dependent} -> {upstream}")
        if relation.deleted or not relation.enabled or not relation.correlation_enabled:
            raise RuntimeError(
                f"Owned dependency {dependent} -> {upstream} is disabled/deleted; fix it before reseeding"
            )
        return relation

    return m.ServiceDependency.create(
        service=service.id,
        depends_on_service=depends_on.id,
        dependency_type=dep_type,
        criticality=criticality,
        correlation_enabled=True,
        propagation_delay_seconds=600,
        description=f"{prefix}: reproducible alert correlation",
        metadata={"correlation_demo_owner": tag},
        enabled=True,
    )


def _group_key(tag, scenario):
    return f"{tag}:alert-group:{scenario}"


def _ensure_group_event(group, event_type, message, at):
    event = m.AlertEvent.get_or_none(
        (m.AlertEvent.group == group.id)
        & (m.AlertEvent.event_type == event_type)
        & (m.AlertEvent.message == message)
    )
    if event is None:
        m.AlertEvent.create(
            group=group.id,
            event_type=event_type,
            message=message,
            created_at=at,
        )
    else:
        event.created_at = at
        event.save(only=[m.AlertEvent.created_at])


def _alert_group(*, team, service, prefix, tag, scenario, alertname,
                 severity, priority, status, first_seen, last_seen,
                 occurrences, acknowledged_at=None, resolved_at=None):
    """Upsert a synthetic AlertGroup and its individual child Alerts, never page."""
    key = _group_key(tag, scenario)
    group = m.AlertGroup.get_or_none(
        (m.AlertGroup.team == team.id)
        & (m.AlertGroup.source == DEMO_SOURCE)
        & (m.AlertGroup.group_key_hash == alerts_repo.hash_group_key(key))
    )
    fields = {
        "team": team.id,
        "service": service.id,
        "source": DEMO_SOURCE,
        "group_key_hash": alerts_repo.hash_group_key(key),
        "group_key": key,
        "title": f"[Demo] {alertname}",
        "message": f"Synthetic {alertname} signal for correlation scenario {scenario}",
        "severity": severity,
        "status": status,
        "priority_slug": priority,
        "priority_order": int(priority[-1]),
        "common_labels": {
            "alertname": alertname,
            "service": service.slug,
            "environment": service.environment,
            "demo_seed": prefix,
            "correlation_demo_owner": tag,
        },
        "label_values": {},
        "payload_summary": {
            "alertname": alertname,
            "correlation_demo_owner": tag,
            "scenario": scenario,
        },
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "acknowledged_at": acknowledged_at,
        "resolved_at": resolved_at,
        "alert_count": occurrences,
        "firing_count": occurrences if status in {"firing", "acknowledged"} else 0,
        "acknowledged_count": 0,
        "resolved_count": occurrences if status == "resolved" else 0,
        "silenced_count": 0,
        "maintenance_suppressed": False,
        "orchestration_suppressed": False,
        "notification_pending": False,
        "notification_due_at": None,
        "notification_reason": None,
        "next_escalation_at": None,
        "merged_into": None,
    }
    if group is None:
        group = m.AlertGroup.create(**fields)
    else:
        _check_owner(group.payload_summary, tag, f"alert group {group.id}")
        if group.service_id != service.id or group.group_key != key:
            raise RuntimeError(f"Refusing to modify foreign alert group #{group.id}")
        if group.merged_into_id is not None or group.status == "merged":
            raise RuntimeError(f"Seeded alert group #{group.id} was merged; refusing to unmerge")
        for name, value in fields.items():
            setattr(group, name, value)
        group.save()

    # Never rewrite or attach non-seed children that may have been added later.
    child_q = m.Alert.select().where(m.Alert.group == group.id)
    children = list(child_q)
    for child in children:
        _check_owner(child.labels, tag, f"child alert {child.id}")
    if len(children) > occurrences:
        raise RuntimeError(
            f"Demo alert group #{group.id} contains extra children. "
            "Choose a different prefix or history count."
        )

    child_status = "resolved" if status == "resolved" else "firing"
    for index in range(occurrences):
        dedup = f"{tag}:child:{scenario}:{index:03d}"
        child = m.Alert.get_or_none(
            (m.Alert.source == DEMO_SOURCE) & (m.Alert.dedup_key == dedup)
        )
        child_first = first_seen + timedelta(minutes=index)
        child_fields = {
            "team": team.id,
            "service": service.id,
            "group": group.id,
            "source": DEMO_SOURCE,
            "external_id": dedup,
            "dedup_key": dedup,
            "group_key": key,
            "title": alertname,
            "message": f"Synthetic child occurrence {index + 1} of {alertname}",
            "severity": severity,
            "priority_slug": priority,
            "priority_order": int(priority[-1]),
            "labels": {
                "alertname": alertname,
                "service": service.slug,
                "environment": service.environment,
                "demo_seed": prefix,
                "correlation_demo_owner": tag,
            },
            "payload": {"demo": True, "scenario": scenario},
            "status": child_status,
            "first_seen_at": child_first,
            "last_seen_at": last_seen,
            "resolved_at": resolved_at,
            "next_escalation_at": None,
        }
        if child is None:
            m.Alert.create(**child_fields)
        else:
            _check_owner(child.labels, tag, f"child alert {child.id}")
            if child.group_id != group.id:
                raise RuntimeError(f"Demo child {child.id} belongs to another group")
            for name, value in child_fields.items():
                setattr(child, name, value)
            child.save()

    actual = m.Alert.select().where(m.Alert.group == group.id).count()
    if actual != occurrences:
        raise RuntimeError(f"Unexpected child count for group {group.id}: {actual} != {occurrences}")

    _ensure_group_event(group, "created", f"[{tag}] Synthetic alert group created", first_seen)
    if acknowledged_at:
        _ensure_group_event(group, "acknowledged", f"[{tag}] Synthetic acknowledgement", acknowledged_at)
    if resolved_at:
        _ensure_group_event(group, "resolved", f"[{tag}] Synthetic resolution", resolved_at)
    return group


def _deployment_event(service, tag, *, key, event_type, at, title, sha):
    """Write GitLab-like timeline fixture; does NOT run deployment correlation."""
    dedup = f"{tag}:deployment:{key}:{event_type}"
    event = m.ServiceEvent.get_or_none(
        (m.ServiceEvent.service == service.id)
        & (m.ServiceEvent.source == DEPLOY_SOURCE)
        & (m.ServiceEvent.dedup_key == dedup)
    )
    values = {
        "service": service.id,
        "group": service.group_id,
        "team": service.team_id,
        "category": "deployment",
        "event_type": event_type,
        "title": title,
        "summary": "Demo deployment context only; temporal proximity is not causation.",
        "source": DEPLOY_SOURCE,
        "source_ref": key,
        "dedup_key": dedup,
        "external_url": "https://gitlab.example.invalid/demo/-/deployments",
        "actor_type": "system",
        "actor_label": "GitLab CI (demo fixture)",
        "status": "success",
        "occurred_at": at,
        "payload": {
            "correlation_demo_owner": tag,
            "provider": "gitlab",
            "project_id": 101,
            "environment": "production",
            "deployment_id": key,
            "commit_sha": sha,
            "synthetic": True,
        },
    }
    if event is None:
        return m.ServiceEvent.create(**values)
    _check_owner(event.payload, tag, f"service event {event.id}")
    for name, value in values.items():
        setattr(event, name, value)
    event.save()
    return event


def _seed_optional_incident(tag, prefix, groups):
    """Link correlated alert groups to an operational Incident via domain API."""
    from app.modules.db import incident_core_repo, incidents_repo
    from app.services.incidents.core import (
        create_incident_from_alert_group,
        link_alert_group,
    )

    root = groups["postgres-root"]
    active_link = incident_core_repo.active_link_for_group(root.id)
    if active_link:
        incident = active_link.incident
        if not (incident.title or "").startswith(f"[{tag}]"):
            raise RuntimeError(
                "Demo root group is linked to a non-demo Incident; not modifying it"
            )
    else:
        priority = incidents_repo.get_priority_by_slug("p1")
        if priority is None:
            raise RuntimeError(
                "--with-incident requires configured incident priorities (p1). "
                "Use the normal initial setup/migrations first."
            )
        incident = create_incident_from_alert_group(
            root.id,
            title=f"[{tag}] Checkout outage after database saturation",
            description="Synthetic operational incident, linked to correlated technical alerts",
            priority_slug="p1",
        )

    for key in ("checkout-symptom", "storefront-symptom"):
        group = groups[key]
        link = incident_core_repo.active_link_for_group(group.id)
        if link and link.incident_id != incident.id:
            raise RuntimeError(f"Demo group {group.id} already belongs to a different Incident")
        if not link:
            link_alert_group(incident.id, group.id, relation_type="related")
    return incident


def seed_correlation_demo(*, team_id: int, prefix="corrdemo", history_groups=36,
                          history_days=30, seed=23, with_incident=False,
                          now: datetime | None = None) -> dict:
    """Seed a single team's demo records and verify real saved correlations.

    The caller must configure/open the Peewee database before invoking. No
    migrations or network calls take place; transaction rolls back on failure.
    """
    if int(team_id) <= 0:
        raise ValueError("team_id must be positive")
    if not 0 <= int(history_groups) <= 500:
        raise ValueError("history_groups must be between 0 and 500")
    if not 1 <= int(history_days) <= 365:
        raise ValueError("history_days must be between 1 and 365")
    prefix = validate_prefix(prefix)
    tag = _tag(prefix, int(team_id))
    now = (now or utc_now()).replace(microsecond=0)
    rng = random.Random(seed)

    with database_proxy.atomic():
        team = m.Team.get_or_none(
            (m.Team.id == team_id)
            & (m.Team.active == True)  # noqa: E712
            & (m.Team.deleted == False)  # noqa: E712
        )
        if team is None or not team.group_id:
            raise ValueError("team not found, inactive or has no group")

        services = {
            spec[0]: _service(team, prefix, tag, spec)
            for spec in SERVICE_SPECS
        }
        for dependency_spec in DEPENDENCIES:
            _dependency(services, prefix, tag, dependency_spec)

        groups = {}
        for (key, service_key, alertname, severity, priority, status,
             first_age, last_age, n, ack_minutes) in ACTIVE_SCENARIOS:
            started = now - timedelta(minutes=first_age)
            observed = now - timedelta(minutes=last_age)
            groups[key] = _alert_group(
                team=team, service=services[service_key],
                prefix=prefix, tag=tag, scenario=key,
                alertname=alertname, severity=severity, priority=priority,
                status=status, first_seen=started, last_seen=observed,
                occurrences=n,
                acknowledged_at=(started + timedelta(minutes=ack_minutes))
                if ack_minutes is not None else None,
            )

        # Historical closed groups populate the lifecycle/noise/ACK analytics;
        # the correlation engine appropriately ignores these resolved groups.
        for index in range(history_groups):
            service_key, alertname, severity, priority = rng.choice(HISTORY_ALERTS)
            day_age = index % history_days
            first = now - timedelta(days=day_age, hours=rng.randrange(4, 20))
            n = rng.randint(1, 9)
            ack = (first + timedelta(minutes=rng.randint(3, 42))) \
                if index % 3 else None
            resolved = first + timedelta(minutes=rng.randint(70, 180))
            scenario = f"historical-{index:03d}"
            groups[scenario] = _alert_group(
                team=team, service=services[service_key],
                prefix=prefix, tag=tag, scenario=scenario,
                alertname=alertname, severity=severity, priority=priority,
                status="resolved", first_seen=first, last_seen=resolved,
                occurrences=n, acknowledged_at=ack, resolved_at=resolved,
            )

        deployment_events = [
            _deployment_event(
                services["checkout"], tag, key="deploy-103", event_type="deployment.succeeded",
                at=now - timedelta(minutes=29),
                title="[Demo] Checkout API deployment v2.13.0", sha="a8b31e2000000000000000000000000000000000",
            ),
            _deployment_event(
                services["checkout"], tag, key="rollback-104", event_type="deployment.succeeded",
                at=now - timedelta(minutes=1),
                title="[Demo] Checkout API rollback v2.12.9", sha="bf08343000000000000000000000000000000000",
            ),
            _deployment_event(
                services["monitoring"], tag, key="unrelated-105", event_type="deployment.succeeded",
                at=now - timedelta(days=2),
                title="[Demo] Unrelated monitoring deployment", sha="11f9222000000000000000000000000000000000",
            ),
        ]

        # Produce real persisted correlation rows via the production engine;
        # do not manufacture correlation records or claim causality.
        for key in ("postgres-root", "redis-root", "checkout-symptom", "storefront-symptom", "isolated"):
            refresh_alert_group_correlations(groups[key])

        expected = [
            ("postgres-root", "checkout-symptom", 1),
            ("postgres-root", "storefront-symptom", 2),
            ("redis-root", "checkout-symptom", 1),
        ]
        for root_key, related_key, depth in expected:
            exists = m.AlertGroupCorrelation.select().where(
                (m.AlertGroupCorrelation.root_group == groups[root_key].id)
                & (m.AlertGroupCorrelation.related_group == groups[related_key].id)
                & (m.AlertGroupCorrelation.relation_type == "possible_root_cause")
                & (m.AlertGroupCorrelation.depth == depth)
                & (m.AlertGroupCorrelation.active == True)  # noqa: E712
            ).exists()
            if not exists:
                raise RuntimeError(
                    f"Correlation engine did not link {root_key} -> {related_key} "
                    f"(depth={depth}); check dependencies and the service environment"
                )

        if m.AlertGroupCorrelation.select().where(
            ((m.AlertGroupCorrelation.root_group == groups["isolated"].id)
             | (m.AlertGroupCorrelation.related_group == groups["isolated"].id))
            & (m.AlertGroupCorrelation.active == True)  # noqa: E712
        ).exists():
            raise RuntimeError("Unrelated control group unexpectedly correlated")

        incident = _seed_optional_incident(tag, prefix, groups) if with_incident else None

        our_group_ids = [group.id for group in groups.values()]
        active_correlations = m.AlertGroupCorrelation.select().where(
            (m.AlertGroupCorrelation.root_group.in_(our_group_ids))
            & (m.AlertGroupCorrelation.related_group.in_(our_group_ids))
            & (m.AlertGroupCorrelation.active == True)  # noqa: E712
        ).count()
        raw_count = m.Alert.select().where(m.Alert.group.in_(our_group_ids)).count()

        return {
            "team_id": team.id,
            "prefix": prefix,
            "services": {name: service.id for name, service in services.items()},
            "alert_groups": len(groups),
            "child_alerts": raw_count,
            "saved_active_correlations": active_correlations,
            "historical_resolved_groups": history_groups,
            "deployment_timeline_events": len(deployment_events),
            "deployment_alert_correlation_implemented": False,
            "example_alert_group_urls": {
                key: f"/alerts/{groups[key].id}"
                for key in ("postgres-root", "checkout-symptom", "storefront-symptom", "isolated")
            },
            "example_incident_url": f"/incidents/{incident.id}" if incident else None,
            "external_delivery": "not triggered",
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-id", type=int, required=True, help="Existing active team ID")
    parser.add_argument("--prefix", default="corrdemo", help="Isolated seed slug prefix")
    parser.add_argument("--history-groups", type=int, default=36)
    parser.add_argument("--history-days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--with-incident", action="store_true", help="Create a linked operational Incident")
    parser.add_argument("--dry-run", action="store_true", help="Print plan; do not connect or write")
    parser.add_argument("--yes", action="store_true", help="Allow writing the configured database")
    args = parser.parse_args(argv)
    try:
        prefix = validate_prefix(args.prefix)
        if args.team_id <= 0 or not 0 <= args.history_groups <= 500 or not 1 <= args.history_days <= 365:
            parser.error("invalid team-id/history-groups/history-days")
        if args.dry_run:
            print(json.dumps({
                "write": False, "team_id": args.team_id, "prefix": prefix,
                "services": 5, "dependencies": 3,
                "active_groups": len(ACTIVE_SCENARIOS), "historical_groups": args.history_groups,
                "deployment_timeline_events": 3,
                "with_incident": args.with_incident,
                "note": "No data is modified; confirm destination DB before --yes.",
            }, indent=2))
            return 0
        if not args.yes:
            parser.error("This changes the configured DB; use --dry-run first, then --yes")
        db = init_database()
        db.connect(reuse_if_open=True)
        try:
            result = seed_correlation_demo(
                team_id=args.team_id, prefix=prefix,
                history_groups=args.history_groups, history_days=args.history_days,
                seed=args.seed, with_incident=args.with_incident,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        finally:
            if not db.is_closed():
                db.close()
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
