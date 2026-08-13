#!/usr/bin/env python3
"""
Populate IncidentRelay release/2.0 with a rich, interconnected demo dataset.

The script is intentionally idempotent: objects are identified by deterministic
demo names/slugs/keys and are updated instead of duplicated on repeated runs.

External delivery is SAFE BY DEFAULT:
- notification channels are created disabled;
- orchestrations are published and enabled in shadow mode;
- orchestration webhook actions use example.invalid and are not queued by shadow executions;
- calendar feeds are created disabled;
- no real network requests are made by this script.

Typical usage:

    python scripts/seed_full_demo_data.py --yes

Useful options:

    --users 20
    --routes 10
    --alerts 200
    --prefix demo
    --seed 42
    --password "Demo123!"
    --enable-channels   # NOT recommended outside an isolated demo environment
    --dry-run

The script targets the IncidentRelay release/2.0 data model.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import timedelta
from typing import Any, Iterable

from app.db import init_database
from app.login import hash_password
from app.modules.common import utc_now
from app.modules.db import models as m
from app.modules.db.migrations import migrate
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.integrations.auth import hash_token
from app.services.service_catalog.presets import ensure_basic_operational_standard


SUPPORTED_ROUTE_SOURCES = (
    "alertmanager",
    "grafana",
    "datadog",
    "rmon",
    "aws_sns",
    "zabbix",
    "webhook",
    "uptime_kuma",
    "sentry",
    "librenms",
)

CHANNEL_TYPES = (
    "slack",
    "mattermost",
    "telegram",
    "webhook",
    "discord",
    "teams",
    "email",
)

LOCALES = ("en", "ru", "de", "fr")
THEMES = ("system", "light", "dark")
TIMEZONES = (
    "UTC",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Moscow",
    "Asia/Almaty",
    "America/New_York",
)

SEVERITIES = ("critical", "warning", "info")

SEED_SCRIPT_VERSION = "2026-08-07-orchestration-v4"

TEAM_BLUEPRINTS = (
    ("platform", "Platform Engineering"),
    ("sre", "Site Reliability"),
    ("checkout", "Checkout"),
    ("payments", "Payments"),
    ("data", "Data Platform"),
    ("customer", "Customer Operations"),
)

SERVICE_NAMES = (
    ("api-gateway", "API Gateway", "api"),
    ("identity", "Identity Service", "api"),
    ("kubernetes", "Kubernetes Platform", "infrastructure"),
    ("postgresql", "PostgreSQL", "database"),
    ("redis", "Redis", "cache"),
    ("rabbitmq", "RabbitMQ", "queue"),
    ("checkout-api", "Checkout API", "api"),
    ("web-storefront", "Web Storefront", "web"),
    ("orders", "Order Service", "api"),
    ("payments-api", "Payments API", "api"),
    ("fraud", "Fraud Detection", "worker"),
    ("billing", "Billing", "api"),
    ("etl", "ETL Pipeline", "worker"),
    ("warehouse", "Data Warehouse", "database"),
    ("kafka", "Kafka", "queue"),
    ("support-portal", "Support Portal", "web"),
    ("crm-sync", "CRM Sync", "worker"),
    ("public-status", "Public Status API", "api"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed IncidentRelay release/2.0 with a full demo dataset."
    )
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--routes", type=int, default=10)
    parser.add_argument("--alerts", type=int, default=200)
    parser.add_argument("--prefix", default="demo")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--password", default="Demo123!")
    parser.add_argument("--enable-channels", action="store_true")
    parser.add_argument("--no-migrate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm that demo data may be written to the configured database.",
    )
    return parser.parse_args()


def _field_names(model: type) -> set[str]:
    return set(model._meta.fields.keys())


def _filtered(model: type, values: dict[str, Any]) -> dict[str, Any]:
    fields = _field_names(model)
    return {key: value for key, value in values.items() if key in fields}


def _where(model: type, identity: dict[str, Any]):
    expression = None
    for name, value in identity.items():
        field = getattr(model, name)
        condition = field == value
        expression = condition if expression is None else expression & condition
    return expression


def ensure(
    model: type,
    identity: dict[str, Any],
    defaults: dict[str, Any] | None = None,
    *,
    update: bool = True,
):
    """Create or update a deterministic demo object."""
    defaults = defaults or {}
    identity = _filtered(model, identity)
    defaults = _filtered(model, defaults)

    obj = model.get_or_none(_where(model, identity))

    if obj is None:
        payload = dict(identity)
        payload.update(defaults)
        if "deleted" in _field_names(model):
            payload.setdefault("deleted", False)
        obj = model.create(**payload)
        return obj, True

    changed = False

    if update:
        for key, value in defaults.items():
            setattr(obj, key, value)
            changed = True

    if hasattr(obj, "deleted") and obj.deleted:
        obj.deleted = False
        changed = True

    if hasattr(obj, "deleted_at") and obj.deleted_at is not None:
        obj.deleted_at = None
        changed = True

    if changed:
        obj.save()

    return obj, False


def ensure_relation(
    model: type,
    identity: dict[str, Any],
    defaults: dict[str, Any] | None = None,
):
    return ensure(model, identity, defaults, update=True)[0]


def model_exists(name: str) -> bool:
    return getattr(m, name, None) is not None


def deterministic_token(prefix: str, purpose: str) -> str:
    clean = purpose.replace(" ", "-").replace("/", "-")
    return f"ir-{prefix}-{clean}-demo-token-2026"


def make_channel_config(channel_type: str, index: int) -> dict[str, Any]:
    base = {
        "notify_on_severities": ["critical", "warning", "info"],
        "demo": True,
    }

    if channel_type == "slack":
        return {
            **base,
            "mode": "webhook",
            "webhook_url": f"https://example.invalid/demo/slack/{index}",
        }

    if channel_type == "mattermost":
        return {
            **base,
            "mode": "webhook",
            "webhook_url": f"https://example.invalid/demo/mattermost/{index}",
        }

    if channel_type == "telegram":
        return {
            **base,
            "bot_token": f"123456:{'DEMO' + str(index):<12}",
            "chat_id": f"-1000000{index:04d}",
        }

    if channel_type in {"webhook", "discord", "teams"}:
        return {
            **base,
            "webhook_url": f"https://example.invalid/demo/{channel_type}/{index}",
        }

    if channel_type == "email":
        return {
            **base,
            "to": [f"demo-alerts-{index}@example.invalid"],
            "subject_prefix": "[IR DEMO]",
        }

    return base


def group_slug(prefix: str, name: str) -> str:
    return f"{prefix}-{name}"


def seed_groups(prefix: str):
    specs = (
        ("engineering", "Demo Engineering"),
        ("product", "Demo Product"),
        ("operations", "Demo Operations"),
    )

    groups = []

    for slug, name in specs:
        group, _ = ensure(
            m.Group,
            {"slug": group_slug(prefix, slug)},
            {
                "name": name,
                "description": f"Seeded by {prefix} full demo dataset",
                "active": True,
            },
        )
        ensure_basic_operational_standard(group)
        groups.append(group)

    return groups


def seed_teams(prefix: str, groups: list):
    teams = []
    group_map = {
        "platform": groups[0],
        "sre": groups[0],
        "checkout": groups[1],
        "payments": groups[1],
        "data": groups[2],
        "customer": groups[2],
    }

    for slug, name in TEAM_BLUEPRINTS:
        team, _ = ensure(
            m.Team,
            {"slug": group_slug(prefix, slug)},
            {
                "group": group_map[slug],
                "name": f"Demo {name}",
                "description": f"Demo team for {name}",
                "escalation_enabled": True,
                "escalation_after_reminders": 2,
                "active": True,
            },
        )
        teams.append(team)

    return teams


def seed_users(
    prefix: str,
    user_count: int,
    password: str,
    groups: list,
    teams: list,
):
    users = []
    users_by_team: dict[int, list] = defaultdict(list)
    password_hash = hash_password(password)

    for index in range(user_count):
        username = f"{prefix}.user{index + 1:02d}"
        primary_team = teams[index % len(teams)]
        primary_group = primary_team.group

        user, _ = ensure(
            m.User,
            {"username": username},
            {
                "display_name": f"Demo User {index + 1:02d}",
                "email": f"{username}@example.invalid",
                "phone": f"+155500{index + 1:04d}",
                "timezone": TIMEZONES[index % len(TIMEZONES)],
                "locale": LOCALES[index % len(LOCALES)],
                "theme": THEMES[index % len(THEMES)],
                "password_hash": password_hash,
                "active": True,
                "is_admin": False,
                "active_group": primary_group,
                "mattermost_user_id": f"demo-mm-{index + 1:02d}",
                "slack_user_id": f"UDEMO{index + 1:05d}",
                "telegram_user_id": str(900000 + index + 1),
                "notify_oncall_shift_start_email": True,
                "notify_oncall_shift_end_email": True,
                "notify_oncall_shift_start_mattermost": index % 2 == 0,
            },
        )
        users.append(user)

        group_role = "editor" if index % 5 == 0 else "viewer"
        ensure_relation(
            m.UserGroup,
            {"user": user, "group": primary_group},
            {"role": group_role, "active": True},
        )

        team_role = (
            "manager"
            if index % 7 == 0
            else "responder"
            if index % 3 != 0
            else "viewer"
        )
        ensure_relation(
            m.TeamUser,
            {"team": primary_team, "user": user},
            {"role": team_role, "active": True},
        )
        users_by_team[primary_team.id].append(user)

        # Give every fifth user a second-team membership to make RBAC/team
        # filters more interesting.
        if index % 5 == 0:
            secondary_team = teams[(index + 1) % len(teams)]
            ensure_relation(
                m.UserGroup,
                {"user": user, "group": secondary_team.group},
                {"role": "viewer", "active": True},
            )
            ensure_relation(
                m.TeamUser,
                {"team": secondary_team, "user": user},
                {"role": "responder", "active": True},
            )
            users_by_team[secondary_team.id].append(user)

    return users, users_by_team


def seed_rotations(
    prefix: str,
    teams: list,
    users: list,
    users_by_team: dict[int, list],
    now,
):
    rotations = []
    primary_by_team = {}

    for index, team in enumerate(teams):
        team_users = users_by_team.get(team.id) or users
        members = team_users[: min(5, len(team_users))]

        rotation, _ = ensure(
            m.Rotation,
            {"team": team, "name": f"{prefix}-primary"},
            {
                "description": f"Primary demo rotation for {team.name}",
                "start_at": now - timedelta(days=14),
                "duration_seconds": 86400,
                "reminder_interval_seconds": 900,
                "rotation_type": "daily",
                "interval_value": 1,
                "interval_unit": "days",
                "handoff_time": "09:00",
                "timezone": TIMEZONES[index % len(TIMEZONES)],
                "enabled": True,
            },
        )
        rotations.append(rotation)
        primary_by_team[team.id] = rotation

        for position, user in enumerate(members):
            ensure_relation(
                m.RotationMember,
                {"rotation": rotation, "user": user},
                {"position": position, "active": True},
            )

        if model_exists("RotationLayer"):
            layer, _ = ensure(
                m.RotationLayer,
                {"rotation": rotation, "name": f"{prefix}-business-hours"},
                {
                    "description": "Demo business-hours rotation layer",
                    "priority": 10,
                    "start_at": now - timedelta(days=14),
                    "duration_seconds": 8 * 3600,
                    "rotation_type": "daily",
                    "interval_value": 1,
                    "interval_unit": "days",
                    "handoff_time": "09:00",
                    "timezone": rotation.timezone,
                    "enabled": True,
                },
            )

            if model_exists("RotationLayerMember"):
                for position, user in enumerate(members):
                    existing = (
                        m.RotationLayerMember.select()
                        .where(
                            (m.RotationLayerMember.layer == layer)
                            & (m.RotationLayerMember.user == user)
                            & (m.RotationLayerMember.ends_at.is_null(True))
                        )
                        .first()
                    )
                    if existing is None:
                        m.RotationLayerMember.create(
                            layer=layer,
                            user=user,
                            position=position,
                            active=True,
                            starts_at=now - timedelta(days=14),
                        )
                    else:
                        existing.position = position
                        existing.active = True
                        existing.save()

            if model_exists("RotationLayerRestriction"):
                for weekday in range(5):
                    ensure_relation(
                        m.RotationLayerRestriction,
                        {
                            "layer": layer,
                            "weekday": weekday,
                            "start_time": "09:00",
                            "end_time": "18:00",
                        },
                        {},
                    )

        if members and index < 3:
            override_reason = f"{prefix}: planned coverage override"
            existing_override = (
                m.RotationOverride.select()
                .where(
                    (m.RotationOverride.rotation == rotation)
                    & (m.RotationOverride.reason == override_reason)
                )
                .first()
            )
            if existing_override is None:
                m.RotationOverride.create(
                    rotation=rotation,
                    user=members[-1],
                    starts_at=now + timedelta(hours=2 + index),
                    ends_at=now + timedelta(hours=6 + index),
                    reason=override_reason,
                )
            else:
                existing_override.user = members[-1]
                # Keep the original interval stable across repeated seed runs.
                existing_override.save()

    # Add two extra rotations so the calendar contains competing schedules.
    for extra_index, team in enumerate(teams[:2]):
        team_users = users_by_team.get(team.id) or users
        rotation, _ = ensure(
            m.Rotation,
            {"team": team, "name": f"{prefix}-secondary"},
            {
                "description": f"Secondary demo rotation for {team.name}",
                "start_at": now - timedelta(days=10),
                "duration_seconds": 43200,
                "reminder_interval_seconds": 1800,
                "rotation_type": "daily",
                "interval_value": 1,
                "interval_unit": "days",
                "handoff_time": "21:00",
                "timezone": TIMEZONES[(extra_index + 2) % len(TIMEZONES)],
                "enabled": True,
            },
        )
        rotations.append(rotation)

        for position, user in enumerate(team_users[: min(4, len(team_users))]):
            ensure_relation(
                m.RotationMember,
                {"rotation": rotation, "user": user},
                {"position": position, "active": True},
            )

    return rotations, primary_by_team


def seed_channels(
    prefix: str,
    teams: list,
    enable_channels: bool,
):
    channels_by_team: dict[int, list] = defaultdict(list)
    all_channels = []

    channel_index = 0

    for team in teams:
        for local_index in range(2):
            channel_type = CHANNEL_TYPES[channel_index % len(CHANNEL_TYPES)]
            channel_index += 1

            channel, _ = ensure(
                m.NotificationChannel,
                {
                    "team": team,
                    "name": f"{prefix}-{channel_type}-{local_index + 1}",
                },
                {
                    "group": team.group,
                    "channel_type": channel_type,
                    "config": make_channel_config(channel_type, channel_index),
                    "enabled": bool(enable_channels),
                },
            )
            channels_by_team[team.id].append(channel)
            all_channels.append(channel)

    return all_channels, channels_by_team


def ensure_priorities():
    specs = (
        ("p1", "P1 Critical", 1),
        ("p2", "P2 High", 2),
        ("p3", "P3 Medium", 3),
        ("p4", "P4 Low", 4),
        ("p5", "P5 Informational", 5),
    )
    priorities = {}

    for slug, name, level in specs:
        priority = m.IncidentPriority.get_or_none(
            m.IncidentPriority.slug == slug
        )
        if priority is None:
            priority = m.IncidentPriority.create(
                slug=slug,
                name=name,
                description=f"Seeded default {slug.upper()} priority",
                level=level,
                enabled=True,
                default=slug == "p3",
            )
        priorities[slug] = priority

    return priorities


def seed_escalation_policies(
    prefix: str,
    teams: list,
    users: list,
    users_by_team: dict[int, list],
    primary_rotation_by_team: dict[int, Any],
):
    policies = {}

    for team in teams:
        team_users = users_by_team.get(team.id) or users
        policy, _ = ensure(
            m.EscalationPolicy,
            {"team": team, "name": f"{prefix}-standard-escalation"},
            {
                "description": "Three-level demo escalation policy",
                "enabled": True,
                "repeat_count": 2,
            },
        )

        rotation = primary_rotation_by_team[team.id]
        user = team_users[0]

        ensure_relation(
            m.EscalationPolicyRule,
            {"policy": policy, "position": 0},
            {
                "delay_seconds": 0,
                "target_type": "rotation",
                "target_rotation": rotation,
                "target_user": None,
                "enabled": True,
            },
        )
        ensure_relation(
            m.EscalationPolicyRule,
            {"policy": policy, "position": 1},
            {
                "delay_seconds": 600,
                "target_type": "user",
                "target_rotation": None,
                "target_user": user,
                "enabled": True,
            },
        )
        ensure_relation(
            m.EscalationPolicyRule,
            {"policy": policy, "position": 2},
            {
                "delay_seconds": 1200,
                "target_type": "rotation",
                "target_rotation": rotation,
                "target_user": None,
                "enabled": True,
            },
        )

        policies[team.id] = policy

    return policies


def seed_notification_policies(
    prefix: str,
    teams: list,
    channels_by_team: dict[int, list],
):
    policies = {}

    for team in teams:
        policy, _ = ensure(
            m.NotificationPolicy,
            {"team": team, "name": f"{prefix}-default-notifications"},
            {
                "description": "Demo notification policy with severity rules",
                "enabled": True,
            },
        )
        channels = channels_by_team[team.id]

        critical_rule, _ = ensure(
            m.NotificationPolicyRule,
            {"policy": policy, "name": f"{prefix}-critical"},
            {
                "description": "Critical events",
                "position": 10,
                "event_types": ["created", "updated", "resolved"],
                "matchers": {"labels": {"severity": "critical"}},
                "continue_matching": True,
                "enabled": True,
            },
        )
        all_rule, _ = ensure(
            m.NotificationPolicyRule,
            {"policy": policy, "name": f"{prefix}-all-events"},
            {
                "description": "Fallback events",
                "position": 100,
                "event_types": ["created", "updated", "resolved"],
                "matchers": {},
                "continue_matching": False,
                "enabled": True,
            },
        )

        ensure_relation(
            m.NotificationPolicyRuleChannel,
            {"rule": critical_rule, "channel": channels[0]},
            {},
        )
        ensure_relation(
            m.NotificationPolicyRuleChannel,
            {"rule": all_rule, "channel": channels[-1]},
            {},
        )

        policies[team.id] = policy

    return policies


def seed_priority_policies(
    prefix: str,
    teams: list,
    priorities: dict[str, Any],
):
    policies = {}

    for team in teams:
        policy, _ = ensure(
            m.PriorityPolicy,
            {"team": team, "name": f"{prefix}-priority-policy"},
            {
                "description": "Demo severity-to-priority mapping",
                "enabled": True,
                "default_for_team": True,
                "update_mode": "raise_only",
                "source_priority_mode": "ignore",
                "fallback_mode": "severity_mapping",
                "fallback_priority": priorities["p3"],
            },
        )

        ensure_relation(
            m.PriorityPolicyRule,
            {"policy": policy, "name": f"{prefix}-critical"},
            {
                "description": "Critical demo alerts become P1",
                "position": 10,
                "matchers": {"labels": {"severity": "critical"}},
                "priority": priorities["p1"],
                "enabled": True,
            },
        )
        ensure_relation(
            m.PriorityPolicyRule,
            {"policy": policy, "name": f"{prefix}-warning"},
            {
                "description": "Warning demo alerts become P2",
                "position": 20,
                "matchers": {"labels": {"severity": "warning"}},
                "priority": priorities["p2"],
                "enabled": True,
            },
        )

        policies[team.id] = policy

    return policies


def seed_services(
    prefix: str,
    teams: list,
    users_by_team: dict[int, list],
    rotations: dict[int, Any],
    escalation_policies: dict[int, Any],
    notification_policies: dict[int, Any],
    priority_policies: dict[int, Any],
    channels_by_team: dict[int, list],
    now,
):
    services = []
    services_by_team: dict[int, list] = defaultdict(list)

    for index, (slug, name, service_type) in enumerate(SERVICE_NAMES):
        team = teams[min(index // 3, len(teams) - 1)]
        team_users = users_by_team.get(team.id) or []

        service, _ = ensure(
            m.Service,
            {"team": team, "slug": group_slug(prefix, slug)},
            {
                "group": team.group,
                "name": f"Demo {name}",
                "description": f"Seeded {name} technical service",
                "kind": "technical",
                "lifecycle": "production",
                "service_type": service_type,
                "environment": "production" if index % 4 else "staging",
                "criticality": (
                    "critical"
                    if index % 5 == 0
                    else "high"
                    if index % 3 == 0
                    else "medium"
                ),
                "tier": (
                    "tier_1"
                    if index % 5 == 0
                    else "tier_2"
                    if index % 3 == 0
                    else "tier_3"
                ),
                "status": "operational",
                "status_source": "manual",
                "default_rotation": rotations[team.id],
                "default_escalation_policy": escalation_policies[team.id],
                "notification_policy": notification_policies[team.id],
                "priority_policy": priority_policies[team.id],
                "labels": {
                    "demo_seed": prefix,
                    "team": team.slug,
                    "domain": slug.split("-")[0],
                },
                "tags": ["demo", "production", service_type],
                "metadata": {
                    "repository": f"https://example.invalid/{prefix}/{slug}",
                    "owner": team.name,
                },
                "enabled": True,
                "public": index % 4 == 0,
                "public_name": name if index % 4 == 0 else None,
                "public_description": (
                    f"Public demo status for {name}" if index % 4 == 0 else None
                ),
                "public_order": index * 10,
            },
        )
        services.append(service)
        services_by_team[team.id].append(service)

        ensure_relation(
            m.ServiceChannel,
            {
                "service": service,
                "channel": channels_by_team[team.id][0],
                "purpose": "default",
            },
            {"enabled": True},
        )

        if team_users and model_exists("ServiceOwner"):
            owner = team_users[index % len(team_users)]
            ensure_relation(
                m.ServiceOwner,
                {"service": service, "user": owner, "role": "owner"},
                {
                    "active": True,
                    "notify_on_created": True,
                    "notify_on_priority_change": True,
                    "notify_on_status_change": True,
                    "notify_on_resolved": True,
                    "notify_on_comment": True,
                },
            )

        if model_exists("ServiceRunbook"):
            ensure(
                m.ServiceRunbook,
                {
                    "service": service,
                    "title": f"{prefix}: {name} incident runbook",
                },
                {
                    "description": f"Demo runbook for {name}",
                    "url": f"https://example.invalid/runbooks/{slug}",
                    "severity": "critical",
                    "matchers": {"labels": {"service": service.slug}},
                    "priority": 10,
                    "enabled": True,
                },
            )

        if model_exists("ServiceLink"):
            link_specs = (
                ("dashboard", "Grafana dashboard"),
                ("logs", "Logs"),
                ("repository", "Repository"),
            )
            for link_position, (link_type, label) in enumerate(link_specs):
                ensure(
                    m.ServiceLink,
                    {
                        "service": service,
                        "link_type": link_type,
                        "label": f"{prefix}: {label}",
                    },
                    {
                        "url": f"https://example.invalid/{link_type}/{slug}",
                        "description": f"Demo {label.lower()} for {name}",
                        "priority": 10 + link_position,
                        "enabled": True,
                    },
                )

        if model_exists("ServiceSli") and model_exists("ServiceSlo"):
            sli, _ = ensure(
                m.ServiceSli,
                {"service": service, "slug": f"{prefix}-availability"},
                {
                    "name": f"{prefix}: Availability",
                    "description": "Demo availability SLI based on alert groups",
                    "sli_type": "incident_availability",
                    "source": "incidentrelay_alert_groups",
                    "configuration": {
                        "demo_seed": prefix,
                        "priority_scope": ["p1", "p2"],
                    },
                    "severity": None,
                    "enabled": True,
                },
            )

            slo, _ = ensure(
                m.ServiceSlo,
                {"service": service, "name": f"{prefix}: 99.9% availability"},
                {
                    "description": "Demo 30-day availability objective",
                    "sli": sli,
                    "comparison": "percent_good_gte",
                    "target_percent_basis_points": 9990,
                    "window_days": 30,
                    "exclude_maintenance": True,
                    "include_open_alerts": True,
                    "enabled": True,
                },
            )

            if model_exists("ServiceSloMeasurement"):
                existing_measurements = (
                    m.ServiceSloMeasurement.select()
                    .where(m.ServiceSloMeasurement.slo == slo)
                    .count()
                )
                if existing_measurements == 0:
                    for days_ago in (14, 7, 1):
                        window_end = now - timedelta(days=days_ago)
                        value = 9980 + ((index + days_ago) % 20)
                        m.ServiceSloMeasurement.create(
                            service=service,
                            sli=sli,
                            slo=slo,
                            window_start=window_end - timedelta(days=30),
                            window_end=window_end,
                            status="met" if value >= 9990 else "breached",
                            value_basis_points=value,
                            target_basis_points=9990,
                            good_count=value,
                            total_count=10000,
                            bad_count=10000 - value,
                            pending_count=0,
                            calculated_at=window_end,
                            details={
                                "demo_seed": prefix,
                                "sample": True,
                            },
                        )

    return services, services_by_team


def seed_service_dependencies(prefix: str, services: list):
    dependencies = []

    # Build small DAGs inside each team (three services per team).
    for team_start in range(0, len(services), 3):
        trio = services[team_start:team_start + 3]
        for local_index in range(1, len(trio)):
            service = trio[local_index]
            depends_on = trio[local_index - 1]
            edge_index = team_start + local_index

            dependency, _ = ensure(
                m.ServiceDependency,
                {"service": service, "depends_on_service": depends_on},
                {
                    "dependency_type": "hard" if local_index == 1 else "soft",
                    "criticality": "required" if local_index == 1 else "important",
                    "correlation_enabled": True,
                    "propagation_delay_seconds": 300 + local_index * 60,
                    "description": f"{prefix}: demo dependency",
                    "metadata": {"demo_seed": prefix, "edge": edge_index},
                    "enabled": True,
                },
            )
            dependencies.append(dependency)

    # Add cross-team dependencies only inside the same access Group.
    extra_edges = (
        (3, 0),
        (4, 1),
        (9, 6),
        (10, 7),
        (15, 12),
        (16, 13),
    )

    for source_index, target_index in extra_edges:
        if source_index >= len(services) or target_index >= len(services):
            continue
        service = services[source_index]
        depends_on = services[target_index]
        dependency, _ = ensure(
            m.ServiceDependency,
            {"service": service, "depends_on_service": depends_on},
            {
                "dependency_type": "hard",
                "criticality": "important",
                "correlation_enabled": True,
                "propagation_delay_seconds": 180,
                "description": f"{prefix}: cross-domain dependency",
                "metadata": {"demo_seed": prefix, "cross_domain": True},
                "enabled": True,
            },
        )
        dependencies.append(dependency)

    return dependencies


def seed_business_services(prefix: str, groups: list, teams: list, services: list):
    specs = (
        (
            groups[1],
            teams[2],
            "online-store",
            "Online Store",
            [services[6], services[7], services[8]],
        ),
        (
            groups[1],
            teams[3],
            "payments",
            "Payments",
            [services[9], services[10], services[11]],
        ),
        (
            groups[2],
            teams[4],
            "analytics",
            "Analytics Platform",
            [services[12], services[13], services[14]],
        ),
        (
            groups[2],
            teams[5],
            "customer-support",
            "Customer Support",
            [services[15], services[16], services[17]],
        ),
    )

    business_services = []

    for index, (group, owner_team, slug, name, components) in enumerate(specs):
        business_service, _ = ensure(
            m.BusinessService,
            {"group": group, "slug": group_slug(prefix, slug)},
            {
                "owner_team": owner_team,
                "name": f"Demo {name}",
                "description": f"Business-facing demo service: {name}",
                "status": "operational",
                "status_source": "calculated",
                "criticality": "critical" if index < 2 else "important",
                "tier": "tier_1" if index < 2 else "tier_2",
                "public": True,
                "public_name": name,
                "public_description": f"Public status for demo {name}",
                "public_order": index * 10,
                "labels": {"demo_seed": prefix, "business_domain": slug},
                "metadata": {"demo_seed": prefix},
                "enabled": True,
            },
        )
        business_services.append(business_service)

        for position, service in enumerate(components):
            ensure_relation(
                m.BusinessServiceComponent,
                {
                    "business_service": business_service,
                    "service": service,
                },
                {
                    "component_type": "technical_service",
                    "criticality": "required" if position == 0 else "important",
                    "impact_weight": 100 if position == 0 else 50,
                    "position": position,
                    "status_rule": "inherit",
                    "description": f"{prefix}: component {service.name}",
                    "enabled": True,
                },
            )

        if model_exists("BusinessServiceStatusHistory"):
            existing = (
                m.BusinessServiceStatusHistory.select()
                .where(
                    (m.BusinessServiceStatusHistory.business_service == business_service)
                    & (m.BusinessServiceStatusHistory.message == f"{prefix}: initial demo status")
                )
                .first()
            )
            if existing is None:
                m.BusinessServiceStatusHistory.create(
                    business_service=business_service,
                    old_status="unknown",
                    new_status="operational",
                    status_source="calculated",
                    message=f"{prefix}: initial demo status",
                    impact_score=0,
                    component_snapshot=[],
                )

    return business_services


def seed_matchers_and_routes(
    prefix: str,
    route_count: int,
    teams: list,
    services_by_team: dict[int, list],
    rotations_by_team: dict[int, Any],
    escalation_policies: dict[int, Any],
    channels_by_team: dict[int, list],
):
    if route_count < 1 or route_count > len(SUPPORTED_ROUTE_SOURCES):
        raise SystemExit(
            f"--routes must be between 1 and {len(SUPPORTED_ROUTE_SOURCES)}"
        )

    routes = []
    route_services: dict[int, list] = {}
    route_tokens: dict[str, str] = {}

    for index, source in enumerate(SUPPORTED_ROUTE_SOURCES[:route_count]):
        team = teams[index % len(teams)]
        route_key = f"{prefix}-{source}-{index + 1:02d}"

        matcher, _ = ensure(
            m.MatcherPreset,
            {"team": team, "name": f"{route_key}-matcher"},
            {
                "description": f"Demo matcher for {source}",
                "matchers": {
                    "labels": {
                        "demo_seed": prefix,
                        "route_key": route_key,
                    }
                },
                "enabled": True,
                "version": 1,
            },
        )

        route, _ = ensure(
            m.AlertRoute,
            {"team": team, "name": f"{prefix}-{source}"},
            {
                "source": source,
                "rotation": rotations_by_team[team.id],
                "escalation_policy": escalation_policies[team.id],
                "matcher_preset": matcher,
                "matchers": {
                    "labels": {
                        "demo_seed": prefix,
                        "route_key": route_key,
                    }
                },
                "group_by": ["labels.demo_group"],
                "integration_config": (
                    {
                        "aws_sns": {
                            "topic_arn": (
                                "arn:aws:sns:us-east-1:000000000000:"
                                f"{prefix}-demo-alerts"
                            )
                        }
                    }
                    if source == "aws_sns"
                    else {"demo_seed": prefix}
                ),
                "notification_channel_mode": "route_only",
                "enabled": True,
                "service": services_by_team[team.id][0],
            },
        )

        raw_token = deterministic_token(prefix, f"route-{index + 1}-{source}")
        route.intake_token_prefix = raw_token[:12]
        route.intake_token_hash = hash_token(raw_token)
        route.save()
        route_tokens[route.name] = raw_token

        for channel in channels_by_team[team.id]:
            ensure_relation(
                m.AlertRouteChannel,
                {"route": route, "channel": channel},
                {},
            )

        candidate_services = services_by_team[team.id]
        route_services[route.id] = candidate_services

        for position, service in enumerate(candidate_services):
            ensure(
                m.ServiceMatchRule,
                {
                    "team": team,
                    "route": route,
                    "service": service,
                    "name": f"{route_key}-service-{position + 1}",
                },
                {
                    "position": position,
                    "description": f"Map {source} demo events to {service.name}",
                    "matchers": {"labels": {"service": service.slug}},
                    "enabled": True,
                },
            )

        routes.append(route)

    return routes, route_services, route_tokens


def seed_maintenance(
    prefix: str,
    groups: list,
    teams: list,
    services: list,
    routes: list,
    users: list,
    now,
):
    specs = [
        (
            "active-suppress-notifications",
            "suppress_notifications",
            now - timedelta(minutes=30),
            now + timedelta(hours=4),
            "service",
            services[0],
            True,
            True,
            None,
        ),
        (
            "active-pause-escalation",
            "pause_escalation_only",
            now - timedelta(minutes=15),
            now + timedelta(hours=3),
            "route",
            routes[min(1, len(routes) - 1)],
            True,
            True,
            None,
        ),
        (
            "active-maintenance-incident",
            "create_maintenance_incident",
            now - timedelta(minutes=20),
            now + timedelta(hours=2),
            "team",
            teams[2],
            False,
            True,
            None,
        ),
        (
            "future-suppress-incident",
            "suppress_incident",
            now + timedelta(days=1),
            now + timedelta(days=1, hours=3),
            "route",
            routes[min(3, len(routes) - 1)],
            False,
            True,
            None,
        ),
        (
            "future-service-maintenance",
            "suppress_notifications",
            now + timedelta(days=2),
            now + timedelta(days=2, hours=6),
            "service",
            services[7],
            False,
            True,
            None,
        ),
        (
            "weekend-recurring",
            "suppress_notifications",
            now + timedelta(days=3),
            now + timedelta(days=3, hours=4),
            "group",
            groups[0],
            False,
            True,
            "FREQ=WEEKLY;COUNT=8",
        ),
        (
            "future-retained",
            "pause_escalation_only",
            now + timedelta(days=4),
            now + timedelta(days=4, hours=2),
            "team",
            teams[4],
            False,
            False,
            None,
        ),
        (
            "future-route-maintenance",
            "create_maintenance_incident",
            now + timedelta(days=5),
            now + timedelta(days=5, hours=5),
            "route",
            routes[-1],
            False,
            True,
            None,
        ),
    ]

    windows = []

    for index, (
        slug,
        behavior,
        starts_at,
        ends_at,
        scope_type,
        scope_obj,
        apply_to_existing,
        reactivate_on_end,
        rrule,
    ) in enumerate(specs):
        active = starts_at <= now < ends_at
        window, _ = ensure(
            m.MaintenanceWindow,
            {"name": f"{prefix}-{slug}"},
            {
                "group": (
                    scope_obj
                    if scope_type == "group"
                    else getattr(scope_obj, "group", None)
                    or getattr(getattr(scope_obj, "team", None), "group", None)
                ),
                "team": (
                    scope_obj
                    if scope_type == "team"
                    else getattr(scope_obj, "team", None)
                ),
                "description": f"Demo maintenance: {slug}",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "timezone": "UTC",
                "rrule": rrule,
                "behavior": behavior,
                "status": "active" if active else "scheduled",
                "enabled": True,
                "apply_to_existing": (
                    False if behavior == "suppress_incident" else apply_to_existing
                ),
                "reactivate_on_end": reactivate_on_end,
                "created_by": users[index % len(users)],
            },
        )
        windows.append(window)

        scope_payload = {
            "maintenance_window": window,
            "scope_type": scope_type,
            "group": scope_obj if scope_type == "group" else None,
            "team": scope_obj if scope_type == "team" else None,
            "service": scope_obj if scope_type == "service" else None,
            "route": scope_obj if scope_type == "route" else None,
        }
        ensure_relation(
            m.MaintenanceWindowScope,
            {
                "maintenance_window": window,
                "scope_type": scope_type,
                **{
                    key: value
                    for key, value in scope_payload.items()
                    if key in {"group", "team", "service", "route"} and value
                },
            },
            {},
        )

        if scope_type == "service" and model_exists("MaintenanceWindowService"):
            ensure_relation(
                m.MaintenanceWindowService,
                {"maintenance_window": window, "service": scope_obj},
                {},
            )

    return windows


def seed_silences(
    prefix: str,
    teams: list,
    routes: list,
    users: list,
    now,
):
    silences = []

    for index in range(min(6, len(routes))):
        route = routes[index]
        team = route.team

        if index < 2:
            starts_at = now - timedelta(hours=1)
            ends_at = now + timedelta(hours=3 + index)
        else:
            starts_at = now + timedelta(days=index)
            ends_at = starts_at + timedelta(hours=4)

        preset, _ = ensure(
            m.MatcherPreset,
            {"team": team, "name": f"{prefix}-silence-{index + 1}-matcher"},
            {
                "description": "Demo silence matcher",
                "matchers": {
                    "labels": {
                        "demo_seed": prefix,
                        "silence_bucket": f"bucket-{index + 1}",
                    }
                },
                "enabled": True,
            },
        )

        silence, _ = ensure(
            m.Silence,
            {"team": team, "name": f"{prefix}-silence-{index + 1}"},
            {
                "reason": "Demo silence rule",
                "matcher_preset": preset,
                "matchers": {
                    "labels": {
                        "demo_seed": prefix,
                        "silence_bucket": f"bucket-{index + 1}",
                    }
                },
                "starts_at": starts_at,
                "ends_at": ends_at,
                "apply_to_existing": index % 2 == 0,
                "reactivate_on_end": index != 1,
                "created_by": users[index % len(users)],
                "enabled": True,
            },
        )
        silences.append(silence)

    return silences


def seed_heartbeats(
    prefix: str,
    teams: list,
    services_by_team: dict[int, list],
    routes: list,
    users: list,
    now,
):
    if not model_exists("Heartbeat"):
        return [], {}

    heartbeats = []
    heartbeat_tokens = {}

    for index, team in enumerate(teams):
        route = routes[index % len(routes)]
        service = services_by_team[team.id][0]
        raw_token = deterministic_token(prefix, f"heartbeat-{index + 1}")

        heartbeat, _ = ensure(
            m.Heartbeat,
            {"team": team, "slug": f"{prefix}-heartbeat-{index + 1}"},
            {
                "group": team.group,
                "service": service,
                "route": route,
                "name": f"Demo heartbeat {index + 1}",
                "description": "Demo dead-man-switch heartbeat",
                "mode": "interval",
                "expected_interval_seconds": 300,
                "grace_period_seconds": 120,
                "timezone": "UTC",
                "status": "ok" if index != 0 else "new",
                "enabled": True,
                "auto_resolve": True,
                "instance_tracking_enabled": index % 2 == 0,
                "instance_key": "instance",
                "expected_instances_mode": "none",
                "severity": "critical",
                "priority_slug": "p2",
                "token_prefix": raw_token[:12],
                "token_hash": hash_token(raw_token),
                "last_seen_at": now - timedelta(minutes=index + 1),
                "last_payload": {
                    "demo_seed": prefix,
                    "instance": f"worker-{index + 1}",
                },
                "next_expected_at": now + timedelta(minutes=5),
                "labels": {"demo_seed": prefix, "team": team.slug},
                "metadata": {"demo": True},
                "created_by": users[index % len(users)],
            },
        )
        heartbeats.append(heartbeat)
        heartbeat_tokens[heartbeat.slug] = raw_token

        if model_exists("HeartbeatPing"):
            existing = (
                m.HeartbeatPing.select()
                .where(
                    (m.HeartbeatPing.heartbeat == heartbeat)
                    & (m.HeartbeatPing.message == f"{prefix}: seeded heartbeat ping")
                )
                .first()
            )
            if existing is None:
                m.HeartbeatPing.create(
                    heartbeat=heartbeat,
                    received_at=now - timedelta(minutes=2),
                    event_type="ping",
                    status_before="new",
                    status_after="ok",
                    message=f"{prefix}: seeded heartbeat ping",
                    payload={"demo_seed": prefix},
                    remote_addr="127.0.0.1",
                    user_agent="IncidentRelay demo seeder",
                )

    return heartbeats, heartbeat_tokens


def seed_calendar_feeds(prefix: str, teams: list, users: list):
    if not model_exists("CalendarFeed"):
        return {}

    tokens = {}

    for index, team in enumerate(teams):
        raw_token = deterministic_token(prefix, f"calendar-{index + 1}")
        feed, _ = ensure(
            m.CalendarFeed,
            {"team": team, "name": f"{prefix}-calendar"},
            {
                "token_prefix": raw_token[:12],
                "token_hash": hash_token(raw_token),
                "enabled": False,
                "past_days": 14,
                "future_days": 90,
                "created_by": users[index % len(users)],
            },
        )
        tokens[f"team:{team.slug}"] = raw_token

    return tokens


def seed_sso(prefix: str, groups: list, teams: list):
    if not model_exists("SsoProvider"):
        return []

    providers = []

    oidc, _ = ensure(
        m.SsoProvider,
        {"slug": f"{prefix}-oidc"},
        {
            "label": "Demo OIDC",
            "protocol": "oidc",
            "enabled": False,
            "auto_create_users": True,
            "auto_link_by_email": True,
            "require_verified_email": True,
            "sync_group_memberships": True,
            "oidc_metadata_url": "https://example.invalid/.well-known/openid-configuration",
            "oidc_issuer": "https://example.invalid/",
            "client_id": "incidentrelay-demo",
            "extra_config": {"demo_seed": prefix},
        },
    )
    providers.append(oidc)

    saml, _ = ensure(
        m.SsoProvider,
        {"slug": f"{prefix}-saml"},
        {
            "label": "Demo SAML",
            "protocol": "saml",
            "enabled": False,
            "auto_create_users": False,
            "auto_link_by_email": True,
            "saml_idp_entity_id": "https://example.invalid/saml/idp",
            "saml_idp_sso_url": "https://example.invalid/saml/sso",
            "saml_sp_entity_id": "incidentrelay-demo",
            "extra_config": {"demo_seed": prefix},
        },
    )
    providers.append(saml)

    if model_exists("SsoGroupMapping"):
        for provider_index, provider in enumerate(providers):
            group = groups[provider_index % len(groups)]
            team = teams[provider_index % len(teams)]
            ensure_relation(
                m.SsoGroupMapping,
                {
                    "provider": provider,
                    "external_group": f"{prefix}-operators-{provider_index + 1}",
                    "incidentrelay_group": group,
                    "incidentrelay_team": team,
                },
                {
                    "group_role": "editor",
                    "team_role": "responder",
                    "active": True,
                    "priority": 10 + provider_index,
                },
            )

    return providers


def seed_api_tokens(prefix: str, groups: list, teams: list, users: list):
    tokens = {}

    for index in range(min(3, len(teams))):
        raw_token = deterministic_token(prefix, f"api-{index + 1}")
        token, _ = ensure(
            m.ApiToken,
            {"name": f"{prefix}-api-token-{index + 1}"},
            {
                "user": users[index],
                "group": groups[index % len(groups)],
                "team": teams[index],
                "token_prefix": raw_token[:12],
                "token_hash": hash_token(raw_token),
                "scopes": ["alerts:write", "alerts:read"],
                "active": True,
            },
        )
        tokens[token.name] = raw_token

    return tokens


def seed_user_notification_rules(prefix: str, users: list):
    if not model_exists("UserNotificationRule"):
        return

    for index, user in enumerate(users[: min(10, len(users))]):
        ensure(
            m.UserNotificationRule,
            {"user": user, "position": 10},
            {
                "method": "browser_push",
                "delay_seconds": 0,
                "enabled": True,
                "severities": ["critical"],
                "event_types": ["created", "escalated"],
            },
        )
        ensure(
            m.UserNotificationRule,
            {"user": user, "position": 20},
            {
                "method": "email",
                "delay_seconds": 120 + (index % 3) * 60,
                "enabled": True,
                "severities": ["critical", "warning"],
                "event_types": ["created", "resolved"],
            },
        )


def seed_orchestration(prefix: str, groups: list, services: list, users: list):
    """Create rich, published shadow-mode demo orchestrations.

    Existing ``<prefix>-orchestration`` rows from the first version of this
    seeder are upgraded in place.  Each group also receives a service-scoped
    showcase orchestration.  Published rules are evaluated in shadow mode so
    execution traces are recorded without changing alert lifecycle results.
    """
    if not model_exists("EventOrchestration"):
        return [], {}

    from app.modules.db import orchestrations_repo

    orchestrations = []
    tokens = {}

    def first_for_group(model, group):
        query = model.select()
        fields = _field_names(model)
        if "group" in fields:
            query = query.where(model.group == group.id)
        elif "team" in fields:
            query = query.join(m.Team).where(m.Team.group == group.id)
        if "enabled" in fields:
            query = query.where(model.enabled == True)
        if "deleted" in fields:
            query = query.where(model.deleted == False)
        return query.order_by(model.id.asc()).first()

    def group_bundle(group):
        route = first_for_group(m.AlertRoute, group)
        if route is None or route.team is None:
            raise RuntimeError(
                f"Demo orchestration for group {group.slug} requires an enabled route"
            )

        team = route.team
        service = (
            m.Service.select()
            .where(
                (m.Service.team == team.id)
                & (m.Service.enabled == True)
                & (m.Service.deleted == False)
            )
            .order_by(m.Service.id.asc())
            .first()
        )
        escalation = (
            m.EscalationPolicy.select()
            .where(
                (m.EscalationPolicy.team == team.id)
                & (m.EscalationPolicy.enabled == True)
                & (m.EscalationPolicy.deleted == False)
            )
            .order_by(m.EscalationPolicy.id.asc())
            .first()
        )
        notification = (
            m.NotificationPolicy.select()
            .where(
                (m.NotificationPolicy.team == team.id)
                & (m.NotificationPolicy.enabled == True)
                & (m.NotificationPolicy.deleted == False)
            )
            .order_by(m.NotificationPolicy.id.asc())
            .first()
        )
        priority_policy = (
            m.PriorityPolicy.select()
            .where(
                (m.PriorityPolicy.team == team.id)
                & (m.PriorityPolicy.enabled == True)
                & (m.PriorityPolicy.deleted == False)
            )
            .order_by(m.PriorityPolicy.id.asc())
            .first()
        )
        if not all((service, escalation, notification, priority_policy)):
            raise RuntimeError(
                f"Demo orchestration for group {group.slug} requires service and "
                f"policies for route team {team.slug}"
            )
        return {
            "route": route,
            "team": team,
            "service": service,
            "escalation": escalation,
            "notification": notification,
            "priority_policy": priority_policy,
        }

    def webhook_for_group(group, actor):
        action, _ = ensure(
            m.OrchestrationWebhookAction,
            {"group": group, "name": f"{prefix}-diagnostics-webhook"},
            {
                "description": (
                    "Safe demo diagnostics action. The target uses the reserved "
                    "example.invalid domain and demo orchestrations run in shadow mode."
                ),
                "url": f"https://example.invalid/{prefix}/{group.slug}/diagnostics",
                "method": "POST",
                "body_template": (
                    '{"title":"{{ event.title }}",'
                    '"service":"{{ labels.service }}",'
                    '"severity":"{{ event.severity }}",'
                    '"region":"{{ labels.region }}"}'
                ),
                "timeout_seconds": 5,
                "retry_count": 1,
                "private_network_policy": "deny",
                # Publication validation requires referenced actions to be enabled.
                # Shadow executions are never enqueued by attach_runtime_executions().
                "enabled": True,
                "created_by": actor,
            },
        )
        return action

    def global_rules(bundle, webhook_action):
        return [
            {
                "name": "01 · Production triage",
                "description": "Nested production triage with enrichment and child rules.",
                "enabled": True,
                "condition_tree": {
                    "all": [
                        {"field": "labels.environment", "operator": "equals", "value": "production"},
                        {"none": [{"field": "labels.ignore_demo", "operator": "is_true"}]},
                    ]
                },
                "actions": [
                    {
                        "type": "extract_regex",
                        "source": "event.title",
                        "pattern": r"^Demo (?P<incoming_severity>[^:]+):",
                        "on_failure": "continue",
                    },
                    {"type": "copy_field", "source": "labels.service", "name": "service_key"},
                    {"type": "lowercase", "source": "labels.environment", "name": "normalized_environment"},
                    {"type": "set_variable", "name": "decision_flow", "value": "production_triage"},
                    {"type": "set_label", "name": "orchestration_stage", "value": "production-triage"},
                    {"type": "set_custom_field", "name": "orchestration_demo", "value": "global-production-tree"},
                    {
                        "type": "set_grouping",
                        "group_key": "demo:{{ labels.service }}:{{ labels.environment }}:{{ labels.region }}",
                        "strategy": "service-environment-region",
                        "window_seconds": 600,
                    },
                    {
                        "type": "add_note",
                        "template": "Production triage matched {{ event.title }} in {{ labels.region }}",
                    },
                ],
                "processing_mode": "evaluate_children",
                "children": [
                    {
                        "name": "01.1 · Critical P1 path",
                        "description": "Critical events select P1 and response policies.",
                        "enabled": True,
                        "condition_tree": {"field": "event.severity", "operator": "equals", "value": "critical"},
                        "actions": [
                            {"type": "set_priority", "value": "p1"},
                            {"type": "set_escalation_policy", "escalation_policy_id": bundle["escalation"].id},
                            {"type": "set_notification_policy", "notification_policy_id": bundle["notification"].id},
                            {"type": "set_priority_policy", "priority_policy_id": bundle["priority_policy"].id},
                            {"type": "set_label", "name": "response_class", "value": "p1"},
                            {"type": "set_title", "template": "[P1][{{ labels.environment }}] {{ event.title }}"},
                        ],
                        "processing_mode": "children_then_continue",
                        "children": [
                            {
                                "name": "01.1.1 · Enterprise or payments ownership",
                                "description": "Nested OR branch that demonstrates ownership routing.",
                                "enabled": True,
                                "condition_tree": {
                                    "any": [
                                        {"field": "labels.customer_tier", "operator": "equals", "value": "enterprise"},
                                        {"field": "labels.service", "operator": "contains", "value": "payments"},
                                    ]
                                },
                                "actions": [
                                    {"type": "set_team", "team_id": bundle["team"].id},
                                    {"type": "set_route", "route_id": bundle["route"].id},
                                    {"type": "set_service", "service_id": bundle["service"].id},
                                    {"type": "set_label", "name": "ownership_override", "value": "critical-path"},
                                ],
                                "processing_mode": "continue",
                                "children": [],
                            },
                            {
                                "name": "01.1.2 · Diagnostics automation",
                                "description": "Async webhook request candidate for selected critical events.",
                                "enabled": True,
                                "condition_tree": {
                                    "all": [
                                        {"field": "labels.region", "operator": "in", "value": ["eu-central-1", "us-east-1"]},
                                        {"field": "labels.service", "operator": "regex", "value": r".*(api|gateway|payments).*"},
                                    ]
                                },
                                "actions": [
                                    {"type": "enqueue_webhook", "action_id": webhook_action.id},
                                    {"type": "add_note", "template": "Diagnostics candidate: {{ labels.service }} / {{ labels.instance }}"},
                                ],
                                "processing_mode": "continue",
                                "children": [],
                            },
                        ],
                    },
                    {
                        "name": "01.2 · Warning degradation",
                        "description": "Warning events become P2 and use wider grouping.",
                        "enabled": True,
                        "condition_tree": {"field": "event.severity", "operator": "equals", "value": "warning"},
                        "actions": [
                            {"type": "set_priority", "value": "p2"},
                            {"type": "set_label", "name": "degradation_candidate", "value": "true"},
                            {
                                "type": "set_grouping",
                                "group_key": "warning:{{ labels.service }}:{{ labels.environment }}",
                                "window_seconds": 900,
                            },
                        ],
                        "processing_mode": "continue",
                        "children": [],
                    },
                ],
            },
            {
                "name": "02 · Latency / error pressure",
                "description": "Threshold-based severity promotion.",
                "enabled": True,
                "condition_tree": {
                    "all": [
                        {"field": "labels.environment", "operator": "equals", "value": "production"},
                        {
                            "any": [
                                {"field": "labels.latency_ms", "operator": "greater_or_equal", "value": 1200},
                                {"field": "labels.error_rate", "operator": "greater_than", "value": 5},
                            ]
                        },
                    ]
                },
                "actions": [
                    {"type": "set_severity", "value": "critical"},
                    {"type": "set_priority", "value": "p1"},
                    {"type": "set_label", "name": "threshold_promotion", "value": "true"},
                    {
                        "type": "add_note",
                        "template": "Threshold promotion: latency={{ labels.latency_ms }}, errors={{ labels.error_rate }}",
                    },
                ],
                "processing_mode": "continue",
                "children": [],
            },
            {
                "name": "03 · Transient flapping guard",
                "description": "Pause transient warnings for two minutes.",
                "enabled": True,
                "condition_tree": {
                    "all": [
                        {"field": "event.severity", "operator": "equals", "value": "warning"},
                        {"field": "labels.transient", "operator": "is_true"},
                    ]
                },
                "actions": [
                    {"type": "pause", "seconds": 120, "retrigger": "preserve", "reason": "Transient {{ labels.instance }}; wait for self-recovery"}
                ],
                "processing_mode": "stop",
                "children": [],
            },
            {
                "name": "04 · Planned / non-production suppression",
                "description": "Content-aware suppression without a separate Silence.",
                "enabled": True,
                "condition_tree": {
                    "any": [
                        {"field": "labels.planned", "operator": "is_true"},
                        {"field": "labels.environment", "operator": "in", "value": ["staging", "development", "test"]},
                    ]
                },
                "actions": [
                    {"type": "set_label", "name": "noise_control", "value": "suppressed"},
                    {"type": "suppress", "reason": "Planned/non-production event in {{ labels.environment }}"},
                ],
                "processing_mode": "stop",
                "children": [],
            },
            {
                "name": "05 · Synthetic signal drop",
                "description": "Non-catch-all drop example.",
                "enabled": True,
                "condition_tree": {
                    "all": [
                        {"field": "labels.synthetic", "operator": "is_true"},
                        {"field": "labels.demo_seed", "operator": "exists"},
                    ]
                },
                "actions": [
                    {"type": "drop", "reason": "Synthetic demo signal {{ labels.instance }}"}
                ],
                "processing_mode": "stop",
                "children": [],
            },
            {
                "name": "06 · Enterprise customer boost",
                "description": "Business context can promote warning/info events to P1.",
                "enabled": True,
                "condition_tree": {
                    "all": [
                        {"field": "labels.customer_tier", "operator": "equals", "value": "enterprise"},
                        {"field": "event.severity", "operator": "in", "value": ["warning", "info"]},
                    ]
                },
                "actions": [
                    {"type": "set_severity", "value": "critical"},
                    {"type": "set_priority", "value": "p1"},
                    {"type": "set_escalation_policy", "escalation_policy_id": bundle["escalation"].id},
                    {"type": "set_label", "name": "customer_impact", "value": "enterprise"},
                ],
                "processing_mode": "continue",
                "children": [],
            },
            {
                "name": "07 · Sensitive-label cleanup",
                "description": "Existence condition plus label removal.",
                "enabled": True,
                "condition_tree": {"field": "labels.secret", "operator": "exists"},
                "actions": [
                    {"type": "remove_label", "name": "secret"},
                    {"type": "set_label", "name": "redacted_by_orchestration", "value": "true"},
                    {"type": "add_note", "value": "Sensitive demo label removed"},
                ],
                "processing_mode": "continue",
                "children": [],
            },
            {
                "name": "08 · Lifecycle conversion",
                "description": "Content can convert a trigger into a resolve event.",
                "enabled": True,
                "condition_tree": {"field": "labels.demo_lifecycle", "operator": "equals", "value": "resolve"},
                "actions": [
                    {"type": "set_event_action", "value": "resolve"},
                    {"type": "add_note", "value": "Lifecycle marker converted to resolve"},
                ],
                "processing_mode": "stop",
                "children": [],
            },
        ]

    def service_rules(bundle, webhook_action):
        return [
            {
                "name": "01 · Service enrichment",
                "description": "Catch-all service-scoped enrichment.",
                "enabled": True,
                "condition_tree": {},
                "actions": [
                    {"type": "set_label", "name": "service_orchestration", "value": bundle["service"].slug},
                    {"type": "set_custom_field", "name": "service_guardrail", "value": "evaluated"},
                    {"type": "add_note", "template": "Service guardrail evaluated {{ service.name }}"},
                ],
                "processing_mode": "continue",
                "children": [],
            },
            {
                "name": "02 · Service SLO pressure",
                "description": "SLO-like latency/error thresholds select policies and diagnostics.",
                "enabled": True,
                "condition_tree": {
                    "any": [
                        {"field": "labels.latency_ms", "operator": "greater_than", "value": 1500},
                        {"field": "labels.error_rate", "operator": "greater_or_equal", "value": 7},
                    ]
                },
                "actions": [
                    {"type": "set_severity", "value": "critical"},
                    {"type": "set_priority", "value": "p1"},
                    {"type": "set_escalation_policy", "escalation_policy_id": bundle["escalation"].id},
                    {"type": "set_notification_policy", "notification_policy_id": bundle["notification"].id},
                    {"type": "enqueue_webhook", "action_id": webhook_action.id},
                ],
                "processing_mode": "continue",
                "children": [],
            },
            {
                "name": "03 · Regional grouping",
                "description": "Regex and ends-with conditions drive grouping.",
                "enabled": True,
                "condition_tree": {
                    "any": [
                        {"field": "labels.region", "operator": "ends_with", "value": "-1"},
                        {"field": "labels.instance", "operator": "regex", "value": r".*-(0[1-3])$"},
                    ]
                },
                "actions": [
                    {
                        "type": "set_grouping",
                        "group_key": "service:{{ labels.service }}:{{ labels.region }}",
                        "strategy": "service-region",
                        "window_seconds": 300,
                    },
                    {"type": "set_label", "name": "regional_grouping", "value": "true"},
                ],
                "processing_mode": "continue",
                "children": [],
            },
        ]

    def publish_baseline_and_refresh_draft(orchestration, rules, actor, draft_extra):
        """Publish the rich baseline whenever the active definition is stale.

        Older seed versions may already have an ``active_version_id`` pointing
        at a trivial one-rule orchestration.  Merely checking for a missing
        active version therefore does not upgrade an existing demo database.
        Compare deterministic definition hashes instead and publish a new
        immutable version whenever the desired rich baseline differs.
        """
        desired_definition = {
            "schema_version": 1,
            "scope": orchestration.scope,
            "service_id": orchestration.service_id,
            "rules": rules,
        }
        desired_hash = orchestrations_repo.definition_hash(desired_definition)

        active_hash = None
        active_version = None
        if orchestration.active_version_id is not None:
            active_version = m.EventOrchestrationVersion.get_or_none(
                m.EventOrchestrationVersion.id == orchestration.active_version_id
            )
            if active_version is not None:
                active_hash = active_version.definition_hash
                if not active_hash:
                    active_hash = orchestrations_repo.definition_hash(
                        orchestrations_repo.export_version(active_version.id)
                    )

        if active_hash != desired_hash:
            draft = orchestrations_repo.get_or_create_draft(
                orchestration.id,
                actor_id=actor.id,
                comment=(
                    "Upgrade demo orchestration to rich showcase "
                    f"({SEED_SCRIPT_VERSION})"
                ),
            )
            draft = orchestrations_repo.save_draft_definition(
                orchestration.id,
                rules,
                actor_id=actor.id,
                comment=(
                    "Rich demo baseline "
                    f"({SEED_SCRIPT_VERSION})"
                ),
            )
            validation = orchestrations_repo.validate_version(draft.id)
            if not validation["valid"]:
                raise RuntimeError(
                    f"Invalid demo orchestration {orchestration.name}: "
                    + "; ".join(validation["errors"])
                )
            published = orchestrations_repo.publish_draft(
                orchestration.id,
                actor_id=actor.id,
                comment=(
                    "Published rich demo baseline "
                    f"({SEED_SCRIPT_VERSION})"
                ),
            )
            print(
                f"[seed {SEED_SCRIPT_VERSION}] upgraded {orchestration.name}: "
                f"published v{published.version_number} with {len(rules)} root rules"
            )
            orchestration = m.EventOrchestration.get_by_id(orchestration.id)
        else:
            version_number = (
                active_version.version_number
                if active_version is not None
                else "?"
            )
            print(
                f"[seed {SEED_SCRIPT_VERSION}] {orchestration.name}: "
                f"published v{version_number} already matches rich baseline"
            )

        # Keep a visible draft differing from the immutable published version.
        draft = orchestrations_repo.get_or_create_draft(
            orchestration.id,
            actor_id=actor.id,
            comment="Demo draft experiment",
        )
        draft_rules = [*rules, draft_extra]
        draft = orchestrations_repo.save_draft_definition(
            orchestration.id,
            draft_rules,
            actor_id=actor.id,
            comment=(
                "Demo draft experiment "
                f"({SEED_SCRIPT_VERSION})"
            ),
        )
        validation = orchestrations_repo.validate_version(draft.id)
        if not validation["valid"]:
            raise RuntimeError(
                f"Invalid demo orchestration draft {orchestration.name}: "
                + "; ".join(validation["errors"])
            )

        orchestrations_repo.set_runtime_state(
            orchestration.id,
            enabled=True,
            mode="shadow",
            compatibility_mode="hybrid",
        )
        orchestration = m.EventOrchestration.get_by_id(orchestration.id)
        active = m.EventOrchestrationVersion.get_by_id(
            orchestration.active_version_id
        )
        active_rule_count = (
            m.EventOrchestrationRule.select()
            .where(m.EventOrchestrationRule.version == active.id)
            .count()
        )
        draft_rule_count = (
            m.EventOrchestrationRule.select()
            .where(m.EventOrchestrationRule.version == draft.id)
            .count()
        )
        print(
            f"[seed {SEED_SCRIPT_VERSION}] ready {orchestration.name}: "
            f"mode={orchestration.mode}, active=v{active.version_number} "
            f"({active_rule_count} total rules), draft=v{draft.version_number} "
            f"({draft_rule_count} total rules)"
        )
        return orchestration

    for index, group in enumerate(groups):
        actor = users[index % len(users)]
        bundle = group_bundle(group)
        webhook_action = webhook_for_group(group, actor)

        # Upgrade the first seeder's existing orchestration in place.
        orchestration, _ = ensure(
            m.EventOrchestration,
            {"group": group, "name": f"{prefix}-orchestration"},
            {
                "description": (
                    "Rich global showcase: nested conditions, extraction, mutation, "
                    "routing, policies, grouping, pause/suppress/drop and automation."
                ),
                "scope": "global",
                "service": None,
                "created_by": actor,
            },
        )
        rules = global_rules(bundle, webhook_action)
        draft_extra = {
            "name": "99 · DRAFT · Experimental VIP routing",
            "description": "Disabled draft-only rule for Versions / Compare demo.",
            "enabled": False,
            "condition_tree": {
                "all": [
                    {"field": "labels.customer_tier", "operator": "equals", "value": "enterprise"},
                    {"field": "labels.region", "operator": "not_in", "value": ["eu-central-1"]},
                ]
            },
            "actions": [
                {"type": "set_team", "team_id": bundle["team"].id},
                {"type": "set_route", "route_id": bundle["route"].id},
                {"type": "set_label", "name": "experimental_vip_route", "value": "true"},
            ],
            "processing_mode": "continue",
            "children": [],
        }
        orchestration = publish_baseline_and_refresh_draft(
            orchestration,
            rules,
            actor,
            draft_extra,
        )
        orchestrations.append(orchestration)

        # Also create one service-scoped example per group.
        service_orchestration, _ = ensure(
            m.EventOrchestration,
            {"group": group, "name": f"{prefix}-service-orchestration"},
            {
                "description": (
                    "Service-scoped showcase with SLO-like thresholds, grouping "
                    "and diagnostics automation."
                ),
                "scope": "service",
                "service": bundle["service"],
                "created_by": actor,
            },
        )
        s_rules = service_rules(bundle, webhook_action)
        s_draft_extra = {
            "name": "99 · DRAFT · Aggressive latency threshold",
            "description": "Disabled draft-only service experiment.",
            "enabled": False,
            "condition_tree": {"field": "labels.latency_ms", "operator": "greater_than", "value": 800},
            "actions": [
                {"type": "set_priority", "value": "p2"},
                {"type": "set_label", "name": "draft_latency_experiment", "value": "true"},
            ],
            "processing_mode": "continue",
            "children": [],
        }
        service_orchestration = publish_baseline_and_refresh_draft(
            service_orchestration,
            s_rules,
            actor,
            s_draft_extra,
        )
        orchestrations.append(service_orchestration)

        if model_exists("OrchestrationIntakeToken"):
            raw_token = deterministic_token(prefix, f"orchestration-{index + 1}")
            token, _ = ensure(
                m.OrchestrationIntakeToken,
                {"orchestration": orchestration, "name": f"{prefix}-intake"},
                {
                    "token_hash": hash_token(raw_token),
                    "token_prefix": raw_token[:12],
                    "enabled": True,
                    "created_by": actor,
                },
            )
            tokens[f"{group.slug}:{token.name}"] = raw_token

    return orchestrations, tokens

def seed_service_events(prefix: str, services: list, users: list, now):
    if not model_exists("ServiceEvent"):
        return

    for index, service in enumerate(services):
        event_specs = (
            (
                "deployment",
                "deployment.completed",
                "Demo deployment completed",
                now - timedelta(days=(index % 7) + 1),
            ),
            (
                "change",
                "configuration.changed",
                "Demo configuration change",
                now - timedelta(hours=(index % 24) + 1),
            ),
        )

        for event_index, (category, event_type, title, occurred_at) in enumerate(
            event_specs
        ):
            dedup_key = f"{prefix}:{service.slug}:{event_type}:{event_index}"
            existing = (
                m.ServiceEvent.select()
                .where(
                    (m.ServiceEvent.service == service)
                    & (m.ServiceEvent.source == "demo_seed")
                    & (m.ServiceEvent.dedup_key == dedup_key)
                )
                .first()
            )
            if existing is None:
                m.ServiceEvent.create(
                    service=service,
                    group=service.group,
                    team=service.team,
                    category=category,
                    event_type=event_type,
                    title=title,
                    summary=f"{prefix}: seeded service timeline event",
                    source="demo_seed",
                    source_ref=dedup_key,
                    dedup_key=dedup_key,
                    external_url="https://example.invalid/change",
                    actor_type="user",
                    actor_user=users[index % len(users)],
                    severity="info",
                    status="success",
                    occurred_at=occurred_at,
                    payload={"demo_seed": prefix},
                )


def seed_alerts(
    prefix: str,
    alert_count: int,
    routes: list,
    route_services: dict[int, list],
):
    created_results = []
    existing_count = 0

    for index in range(alert_count):
        route = routes[index % len(routes)]
        route_round = index // len(routes)
        services = route_services[route.id]
        service = services[route_round % len(services)]
        severity = SEVERITIES[index % len(SEVERITIES)]

        dedup_key = f"{prefix}:{route.source}:alert:{index + 1:04d}"
        existing = (
            m.Alert.select()
            .where(
                (m.Alert.source == route.source)
                & (m.Alert.dedup_key == dedup_key)
            )
            .first()
        )
        if existing is not None:
            existing_count += 1
            continue

        route_key = f"{prefix}-{route.source}-{routes.index(route) + 1:02d}"
        group_bucket = route_round // 2
        silence_bucket = f"bucket-{(index % min(6, len(routes))) + 1}"

        labels = {
            "demo_seed": prefix,
            "route_key": route_key,
            "demo_group": f"{route_key}-group-{group_bucket:03d}",
            "service": service.slug,
            "team": route.team.slug,
            "severity": severity,
            "environment": service.environment,
            "instance": f"{service.slug}-{(index % 5) + 1:02d}",
            "region": ("eu-central-1", "us-east-1", "ap-southeast-1")[
                index % 3
            ],
            "silence_bucket": silence_bucket,
            "customer_tier": (
                "enterprise" if index % 9 == 0 else
                "business" if index % 4 == 0 else
                "standard"
            ),
            "transient": index % 13 == 0,
            "synthetic": index % 17 == 0,
            "planned": index % 19 == 0,
            "latency_ms": 150 + ((index * 137) % 2400),
            "error_rate": round(((index * 11) % 95) / 10, 1),
            "secret": f"demo-secret-{index + 1}" if index % 23 == 0 else None,
            "demo_lifecycle": "resolve" if index % 31 == 0 else "trigger",
        }

        alert_data = {
            "source": route.source,
            "external_id": f"{prefix}-external-{index + 1:04d}",
            "dedup_key": dedup_key,
            "title": f"Demo {severity}: {service.name} signal {index + 1:04d}",
            "message": (
                f"Seeded demo event from {route.source} for {service.name}. "
                f"Occurrence {index + 1}."
            ),
            "severity": severity,
            "labels": labels,
            "annotations": {
                "summary": f"Demo {service.name} alert",
                "description": "Generated by full demo seed script",
            },
            "payload": {
                "demo_seed": prefix,
                "integration": route.source,
                "route_id": route.id,
                "service_id": service.id,
                "sequence": index + 1,
            },
            "status": "firing",
            "team_slug": route.team.slug,
            "forced_route_id": route.id,
            "forced_team_id": route.team.id,
        }

        result = upsert_alert(alert_data)

        if getattr(result, "alert", None) is None:
            raise RuntimeError(
                f"Demo alert {dedup_key} was not created; "
                f"outcome={getattr(result, 'outcome', None)!r}, "
                f"reason={getattr(result, 'reason', None)!r}"
            )

        created_results.append(result)

    return created_results, existing_count


def seed_orchestration_showcase_alerts(prefix: str, groups: list):
    """Create deterministic v2 showcase alerts after orchestration upgrade.

    This exists specifically for databases already populated by an older seed
    version: the original 200 alerts are not replayed on a second run, so they
    cannot retroactively produce shadow OrchestrationExecution rows.
    """
    if not model_exists("EventOrchestration"):
        return 0, 0

    created = 0
    existing = 0
    cases = (
        {
            "name": "critical-enterprise",
            "severity": "critical",
            "environment": "production",
            "customer_tier": "enterprise",
            "transient": False,
            "synthetic": False,
            "planned": False,
            "latency_ms": 1900,
            "error_rate": 8.2,
        },
        {
            "name": "warning-transient",
            "severity": "warning",
            "environment": "production",
            "customer_tier": "standard",
            "transient": True,
            "synthetic": False,
            "planned": False,
            "latency_ms": 700,
            "error_rate": 2.4,
        },
        {
            "name": "planned-staging",
            "severity": "info",
            "environment": "staging",
            "customer_tier": "business",
            "transient": False,
            "synthetic": False,
            "planned": True,
            "latency_ms": 250,
            "error_rate": 0.2,
        },
        {
            "name": "synthetic-secret",
            "severity": "critical",
            "environment": "production",
            "customer_tier": "standard",
            "transient": False,
            "synthetic": True,
            "planned": False,
            "latency_ms": 1350,
            "error_rate": 5.8,
            "secret": "demo-secret-to-redact",
        },
    )

    for group in groups:
        orchestration = m.EventOrchestration.get_or_none(
            (m.EventOrchestration.group == group.id)
            & (m.EventOrchestration.name == f"{prefix}-orchestration")
            & (m.EventOrchestration.enabled == True)
            & (m.EventOrchestration.mode == "shadow")
        )
        service_orchestration = m.EventOrchestration.get_or_none(
            (m.EventOrchestration.group == group.id)
            & (m.EventOrchestration.name == f"{prefix}-service-orchestration")
        )
        if orchestration is None or service_orchestration is None:
            continue

        route = (
            m.AlertRoute.select()
            .join(m.Team)
            .where(
                (m.Team.group == group.id)
                & (m.AlertRoute.enabled == True)
                & (m.AlertRoute.deleted == False)
            )
            .order_by(m.AlertRoute.id.asc())
            .first()
        )
        service = service_orchestration.service
        if route is None or service is None:
            continue

        matcher_labels = ((route.matchers or {}).get("labels") or {})
        route_key = matcher_labels.get("route_key")

        for case_index, case in enumerate(cases, start=1):
            dedup_key = (
                f"{prefix}:orch-showcase:v2:{group.id}:"
                f"{case_index}:{case['name']}"
            )
            prior = m.Alert.get_or_none(
                (m.Alert.source == route.source)
                & (m.Alert.dedup_key == dedup_key)
            )
            if prior is not None:
                existing += 1
                continue

            labels = {
                "demo_seed": prefix,
                "route_key": route_key,
                "demo_group": f"{prefix}-orch-showcase-{case_index}",
                "service": service.slug,
                "team": route.team.slug,
                "severity": case["severity"],
                "environment": case["environment"],
                "instance": f"showcase-{group.id}-{case_index:02d}",
                "region": ("eu-central-1", "us-east-1", "ap-southeast-1", "eu-west-1")[case_index - 1],
                "customer_tier": case["customer_tier"],
                "transient": case["transient"],
                "synthetic": case["synthetic"],
                "planned": case["planned"],
                "latency_ms": case["latency_ms"],
                "error_rate": case["error_rate"],
                "demo_lifecycle": "trigger",
            }
            if case.get("secret"):
                labels["secret"] = case["secret"]

            result = upsert_alert({
                "source": route.source,
                "external_id": dedup_key,
                "dedup_key": dedup_key,
                "title": (
                    f"Demo {case['severity']}: orchestration showcase "
                    f"{case['name']}"
                ),
                "message": "Generated to populate Event Orchestration shadow executions.",
                "severity": case["severity"],
                "labels": labels,
                "annotations": {
                    "summary": f"Orchestration showcase: {case['name']}",
                    "description": "Seeded after rich orchestration publication",
                },
                "payload": {
                    "demo_seed": prefix,
                    "showcase": True,
                    "case": case["name"],
                },
                "status": "firing",
                "team_slug": route.team.slug,
                "forced_route_id": route.id,
                "forced_team_id": route.team.id,
                "_forced_service_id": service.id,
            })
            if getattr(result, "alert", None) is None:
                raise RuntimeError(
                    f"Could not create orchestration showcase alert {dedup_key}: "
                    f"{getattr(result, 'reason', None)!r}"
                )
            created += 1

    return created, existing


def demo_groups(prefix: str) -> list:
    alerts = (
        m.Alert.select(m.Alert.group)
        .where(m.Alert.dedup_key.startswith(f"{prefix}:"))
        .where(m.Alert.group.is_null(False))
    )
    group_ids = sorted(
        {
            alert.group_id
            for alert in alerts
            if alert.group_id is not None
        }
    )
    return list(
        m.AlertGroup.select()
        .where(m.AlertGroup.id.in_(group_ids))
        .order_by(m.AlertGroup.id)
    )


def seed_alert_group_activity(
    prefix: str,
    groups: list,
    users: list,
    channels_by_team: dict[int, list],
    now,
):
    for index, group in enumerate(groups):
        # Give the dataset a mix of resolved, acknowledged and firing groups.
        if index % 11 == 0 and group.status != "resolved":
            resolve_alert(group.id, user_id=users[index % len(users)].id, update_messages=False)
            group = m.AlertGroup.get_by_id(group.id)
        elif index % 7 == 0 and group.status == "firing":
            acknowledge_alert(group.id, user_id=users[index % len(users)].id)
            group = m.AlertGroup.get_by_id(group.id)

        # Prevent the demo dataset from causing real scheduled delivery later.
        group.notification_pending = False
        group.notification_due_at = None
        group.next_escalation_at = None

        if index % 5 == 0:
            group.last_notification_at = now - timedelta(minutes=30 + index)
            group.last_escalated_at = now - timedelta(minutes=20 + index)
            group.escalation_level = 1
        group.save()

        (
            m.Alert.update(next_escalation_at=None)
            .where(m.Alert.group == group.id)
            .execute()
        )

        if index < 20 and model_exists("AlertComment"):
            body = f"{prefix}: investigation note for alert group {group.id}"
            existing_comment = (
                m.AlertComment.select()
                .where(
                    (m.AlertComment.group == group)
                    & (m.AlertComment.body == body)
                )
                .first()
            )
            if existing_comment is None:
                m.AlertComment.create(
                    group=group,
                    user=users[index % len(users)],
                    body=body,
                )

        if index < 12 and model_exists("IncidentResponder"):
            responder = users[(index + 1) % len(users)]
            existing = (
                m.IncidentResponder.select()
                .where(
                    (m.IncidentResponder.group == group)
                    & (m.IncidentResponder.target_type == "user")
                    & (m.IncidentResponder.target_user == responder)
                )
                .first()
            )
            if existing is None:
                m.IncidentResponder.create(
                    group=group,
                    target_type="user",
                    target_user=responder,
                    requested_by=users[index % len(users)],
                    accepted_by=responder,
                    status="accepted",
                    message=f"{prefix}: demo responder request",
                    response_message="Accepted for demo data",
                    notification_status="sent",
                    requested_at=now - timedelta(minutes=30),
                    responded_at=now - timedelta(minutes=29),
                )

        if index < 12 and model_exists("IncidentStakeholder"):
            stakeholder = users[(index + 2) % len(users)]
            existing = (
                m.IncidentStakeholder.select()
                .where(
                    (m.IncidentStakeholder.group == group)
                    & (m.IncidentStakeholder.user == stakeholder)
                )
                .first()
            )
            if existing is None:
                m.IncidentStakeholder.create(
                    group=group,
                    user=stakeholder,
                    display_name=stakeholder.display_name,
                    role="stakeholder",
                    source="manual",
                    active=True,
                    created_by=users[index % len(users)],
                )

        if index < 15 and model_exists("AlertNotification"):
            team_id = group.team_id
            team_channels = channels_by_team.get(team_id, [])
            if team_channels:
                channel = team_channels[index % len(team_channels)]
                existing = (
                    m.AlertNotification.select()
                    .where(
                        (m.AlertNotification.group == group)
                        & (m.AlertNotification.channel == channel)
                    )
                    .first()
                )
                if existing is None:
                    m.AlertNotification.create(
                        group=group,
                        channel=channel,
                        provider=channel.channel_type,
                        external_message_id=f"{prefix}-msg-{group.id}",
                        external_channel_id=f"{prefix}-channel",
                        last_event_type="created",
                        provider_status="sent",
                        provider_payload={"demo_seed": prefix},
                        created_at=now - timedelta(minutes=45),
                        updated_at=now - timedelta(minutes=45),
                    )


def seed_user_notification_history(
    prefix: str,
    groups: list,
    users: list,
    now,
):
    if not model_exists("UserNotificationDelivery") or not model_exists(
        "UserNotificationRule"
    ):
        return

    for index, group in enumerate(groups[: min(8, len(groups))]):
        user = users[index % len(users)]
        rule = (
            m.UserNotificationRule.select()
            .where(m.UserNotificationRule.user == user)
            .order_by(m.UserNotificationRule.position)
            .first()
        )
        if rule is None:
            continue

        existing = (
            m.UserNotificationDelivery.select()
            .where(
                (m.UserNotificationDelivery.group == group)
                & (m.UserNotificationDelivery.user == user)
                & (m.UserNotificationDelivery.event_type == "created")
                & (m.UserNotificationDelivery.method == rule.method)
            )
            .first()
        )
        if existing is None:
            m.UserNotificationDelivery.create(
                group=group,
                user=user,
                rule=rule,
                method=rule.method,
                event_type="created",
                status="sent",
                scheduled_at=now - timedelta(hours=2),
                sent_at=now - timedelta(hours=2) + timedelta(seconds=10),
                provider=rule.method,
                external_message_id=f"{prefix}-user-notification-{index + 1}",
                provider_status="sent",
                provider_payload={"demo_seed": prefix},
            )


def seed_audit_log(
    prefix: str,
    groups: list,
    teams: list,
    users: list,
    alert_groups: list,
):
    if not model_exists("AuditLog"):
        return

    existing_count = (
        m.AuditLog.select()
        .where(m.AuditLog.action.startswith(f"{prefix}."))
        .count()
    )
    if existing_count:
        return

    actions = (
        "seed.started",
        "route.created",
        "service.created",
        "rotation.created",
        "maintenance.created",
        "silence.created",
        "alert.received",
        "incident.acknowledged",
        "incident.resolved",
        "seed.completed",
    )

    for index in range(30):
        alert_group = alert_groups[index % len(alert_groups)] if alert_groups else None
        team = teams[index % len(teams)]
        m.AuditLog.create(
            group=team.group,
            team=team,
            user=users[index % len(users)],
            action=f"{prefix}.{actions[index % len(actions)]}",
            object_type="alert_group" if alert_group else "seed",
            object_id=alert_group.id if alert_group else None,
            message=f"{prefix}: demo audit event {index + 1}",
            data={
                "demo_seed": prefix,
                "sequence": index + 1,
            },
        )


def refresh_correlations_and_business_status(alert_groups: Iterable, services: Iterable):
    try:
        from app.services.alerts.correlation import (
            refresh_alert_group_correlations_safely,
        )

        for group in alert_groups:
            refresh_alert_group_correlations_safely(
                group,
                reason="demo_seed",
            )
    except Exception as exc:
        print(
            f"WARNING: correlation refresh skipped: {exc}",
            file=sys.stderr,
        )

    try:
        from app.services.business_services.status import (
            refresh_business_services_safely_for_technical_service,
        )

        for service in services:
            refresh_business_services_safely_for_technical_service(
                service.id,
                reason="demo_seed",
            )
    except Exception as exc:
        print(
            f"WARNING: business service status refresh skipped: {exc}",
            file=sys.stderr,
        )


def summary(
    prefix: str,
    *,
    route_tokens: dict[str, str],
    heartbeat_tokens: dict[str, str],
    calendar_tokens: dict[str, str],
    api_tokens: dict[str, str],
    orchestration_tokens: dict[str, str],
    password: str,
):
    counters = {}

    models_to_count = (
        "Group",
        "Team",
        "User",
        "Rotation",
        "RotationLayer",
        "NotificationChannel",
        "EscalationPolicy",
        "NotificationPolicy",
        "PriorityPolicy",
        "MatcherPreset",
        "AlertRoute",
        "Service",
        "ServiceDependency",
        "BusinessService",
        "ServiceMatchRule",
        "MaintenanceWindow",
        "Silence",
        "Heartbeat",
        "AlertGroup",
        "Alert",
        "AlertComment",
        "IncidentResponder",
        "IncidentStakeholder",
        "ServiceSli",
        "ServiceSlo",
        "ServiceRunbook",
        "ServiceLink",
        "ServiceEvent",
        "SsoProvider",
        "EventOrchestration",
        "OrchestrationWebhookAction",
    )

    for model_name in models_to_count:
        model = getattr(m, model_name, None)
        if model is None:
            continue

        # Exact demo-only filtering is different per table, so these are
        # intentionally global totals. The deterministic seed keys below make
        # demo records easy to identify in the UI and database.
        counters[model_name] = model.select().count()

    return {
        "status": "full demo dataset ready",
        "prefix": prefix,
        "demo_user_password": password,
        "database_totals": counters,
        "route_intake_tokens": route_tokens,
        "heartbeat_tokens": heartbeat_tokens,
        "calendar_feed_tokens": calendar_tokens,
        "api_tokens": api_tokens,
        "orchestration_tokens": orchestration_tokens,
        "safety": {
            "external_channels_enabled": False,
            "note": (
                "Channels are disabled unless --enable-channels was explicitly "
                "passed. Event Orchestration runs in shadow mode, so rule results "
                "are traced but not applied and webhook automation is not queued. "
                "Webhook targets use example.invalid. Calendar feeds remain disabled."
            ),
        },
    }


def dry_run_plan(args: argparse.Namespace):
    return {
        "branch_target": "release/2.0",
        "prefix": args.prefix,
        "users": args.users,
        "teams": len(TEAM_BLUEPRINTS),
        "rotations": len(TEAM_BLUEPRINTS) + 2,
        "routes": args.routes,
        "route_sources": list(SUPPORTED_ROUTE_SOURCES[: args.routes]),
        "alerts": args.alerts,
        "technical_services": len(SERVICE_NAMES),
        "business_services": 4,
        "maintenance_windows": 8,
        "silences": min(6, args.routes),
        "also_seeded": [
            "groups and RBAC memberships",
            "rotation layers/restrictions/overrides",
            "notification channels",
            "notification policies",
            "user notification rules/history",
            "escalation policies",
            "incident priorities and priority policies",
            "matcher presets and service match rules",
            "service dependencies",
            "service owners",
            "runbooks and useful links",
            "SLI/SLO definitions and sample measurements",
            "service timeline events",
            "business-service components/status history",
            "heartbeats and ping history",
            "calendar feeds",
            "API tokens",
            "disabled OIDC/SAML providers and mappings",
            "published Event Orchestration + editable drafts",
            "global and service-scoped shadow orchestration",
            "safe orchestration webhook actions targeting example.invalid",
            "orchestration showcase alerts/execution traces",
            "comments, responders and stakeholders",
            "notification history",
            "audit log",
            "dependency correlation/business-impact refresh",
        ],
        "external_channels_enabled": args.enable_channels,
    }


def main() -> int:
    args = parse_args()

    if args.users < 6:
        raise SystemExit("--users must be at least 6")
    if args.alerts < 1:
        raise SystemExit("--alerts must be positive")
    if args.routes < 1 or args.routes > len(SUPPORTED_ROUTE_SOURCES):
        raise SystemExit(
            f"--routes must be between 1 and {len(SUPPORTED_ROUTE_SOURCES)}"
        )

    if args.dry_run:
        print(json.dumps(dry_run_plan(args), indent=2, ensure_ascii=False))
        return 0

    if not args.yes:
        raise SystemExit(
            "This command writes demo data to the configured IncidentRelay "
            "database. Re-run with --yes, or use --dry-run first."
        )

    print(
        f"IncidentRelay demo seeder: {SEED_SCRIPT_VERSION} "
        f"(prefix={args.prefix!r}, routes={args.routes}, alerts={args.alerts})"
    )

    random.seed(args.seed)
    now = utc_now().replace(microsecond=0)

    db = init_database()
    db.connect(reuse_if_open=True)

    try:
        if not args.no_migrate:
            migrate()

        groups = seed_groups(args.prefix)
        teams = seed_teams(args.prefix, groups)
        users, users_by_team = seed_users(
            args.prefix,
            args.users,
            args.password,
            groups,
            teams,
        )

        rotations, primary_rotation_by_team = seed_rotations(
            args.prefix,
            teams,
            users,
            users_by_team,
            now,
        )

        channels, channels_by_team = seed_channels(
            args.prefix,
            teams,
            args.enable_channels,
        )

        priorities = ensure_priorities()

        escalation_policies = seed_escalation_policies(
            args.prefix,
            teams,
            users,
            users_by_team,
            primary_rotation_by_team,
        )
        notification_policies = seed_notification_policies(
            args.prefix,
            teams,
            channels_by_team,
        )
        priority_policies = seed_priority_policies(
            args.prefix,
            teams,
            priorities,
        )

        services, services_by_team = seed_services(
            args.prefix,
            teams,
            users_by_team,
            primary_rotation_by_team,
            escalation_policies,
            notification_policies,
            priority_policies,
            channels_by_team,
            now,
        )

        dependencies = seed_service_dependencies(
            args.prefix,
            services,
        )
        business_services = seed_business_services(
            args.prefix,
            groups,
            teams,
            services,
        )

        routes, route_services, route_tokens = seed_matchers_and_routes(
            args.prefix,
            args.routes,
            teams,
            services_by_team,
            primary_rotation_by_team,
            escalation_policies,
            channels_by_team,
        )

        maintenance_windows = seed_maintenance(
            args.prefix,
            groups,
            teams,
            services,
            routes,
            users,
            now,
        )
        silences = seed_silences(
            args.prefix,
            teams,
            routes,
            users,
            now,
        )

        seed_user_notification_rules(args.prefix, users)
        seed_service_events(args.prefix, services, users, now)

        heartbeats, heartbeat_tokens = seed_heartbeats(
            args.prefix,
            teams,
            services_by_team,
            routes,
            users,
            now,
        )
        calendar_tokens = seed_calendar_feeds(
            args.prefix,
            teams,
            users,
        )
        sso_providers = seed_sso(
            args.prefix,
            groups,
            teams,
        )
        api_tokens = seed_api_tokens(
            args.prefix,
            groups,
            teams,
            users,
        )
        orchestrations, orchestration_tokens = seed_orchestration(
            args.prefix,
            groups,
            services,
            users,
        )

        created_alerts, existing_alert_count = seed_alerts(
            args.prefix,
            args.alerts,
            routes,
            route_services,
        )
        if existing_alert_count:
            # Older seed versions already created the main 200 alerts before
            # rich shadow orchestration existed. Add a small deterministic
            # showcase set so rerunning the upgraded seeder produces traces.
            showcase_alerts_created, showcase_alerts_existing = (
                seed_orchestration_showcase_alerts(args.prefix, groups)
            )
        else:
            showcase_alerts_created = 0
            showcase_alerts_existing = 0

        alert_groups = demo_groups(args.prefix)

        seed_alert_group_activity(
            args.prefix,
            alert_groups,
            users,
            channels_by_team,
            now,
        )
        seed_user_notification_history(
            args.prefix,
            alert_groups,
            users,
            now,
        )
        seed_audit_log(
            args.prefix,
            groups,
            teams,
            users,
            alert_groups,
        )

        refresh_correlations_and_business_status(
            alert_groups,
            services,
        )

        result = summary(
            args.prefix,
            route_tokens=route_tokens,
            heartbeat_tokens=heartbeat_tokens,
            calendar_tokens=calendar_tokens,
            api_tokens=api_tokens,
            orchestration_tokens=orchestration_tokens,
            password=args.password,
        )
        result["seed_run"] = {
            "script_version": SEED_SCRIPT_VERSION,
            "new_alerts_created": len(created_alerts),
            "alerts_already_present": existing_alert_count,
            "orchestration_showcase_alerts_created": showcase_alerts_created,
            "orchestration_showcase_alerts_existing": showcase_alerts_existing,
            "demo_alert_groups": len(alert_groups),
            "dependencies": len(dependencies),
            "business_services": len(business_services),
            "maintenance_windows": len(maintenance_windows),
            "silences": len(silences),
            "heartbeats": len(heartbeats),
            "sso_providers": len(sso_providers),
            "orchestrations": len(orchestrations),
            "channels": len(channels),
            "rotations": len(rotations),
        }
        result["safety"]["external_channels_enabled"] = bool(
            args.enable_channels
        )

        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    finally:
        if not db.is_closed():
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
