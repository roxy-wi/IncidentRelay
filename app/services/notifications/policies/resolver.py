from dataclasses import dataclass, field

from app.modules.db import notification_policies_repo, routes_repo
from app.services.notifications.policies.constants import (
    NOTIFICATION_CHANNEL_MODES,
    ROUTE_ONLY,
    SERVICE_POLICY,
    SERVICE_POLICY_PLUS_ROUTE,
    NOTIFICATION_POLICY_EVENT_ALIASES,
)
from app.services.notifications.policies.matcher import (
    notification_rule_matches,
)


@dataclass
class NotificationChannelResolution:
    """Effective notification channels with resolution details."""

    mode: str
    channels: list = field(default_factory=list)
    service_id: int | None = None
    policy_id: int | None = None
    matched_rule_ids: list[int] = field(default_factory=list)
    channel_sources: dict[int, list[dict]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    rule_errors: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "mode": self.mode,
            "service_id": self.service_id,
            "policy_id": self.policy_id,
            "matched_rule_ids": self.matched_rule_ids,
            "channel_ids": [channel.id for channel in self.channels],
            "channel_sources": self.channel_sources,
            "notes": self.notes,
            "rule_errors": self.rule_errors,
        }


def _channel_is_available(channel):
    if not channel:
        return False

    if not channel.enabled:
        return False

    return not getattr(channel, "deleted", False)


def _add_channel(result, channel, source, rule_id=None):
    if not _channel_is_available(channel):
        return

    if channel.id not in result.channel_sources:
        result.channels.append(channel)
        result.channel_sources[channel.id] = []

    source_data = {"source": source}

    if rule_id is not None:
        source_data["rule_id"] = rule_id

    if source_data not in result.channel_sources[channel.id]:
        result.channel_sources[channel.id].append(source_data)


def _add_route_channels(result, route):
    for link in routes_repo.list_route_channels(route.id):
        _add_channel(result, link.channel, "route")


def _add_service_policy_channels(result, group, event_type):
    service = getattr(group, "service", None)

    if not service:
        result.notes.append("service_missing")
        return

    result.service_id = service.id

    policy_id = getattr(service, "notification_policy_id", None)

    if not policy_id:
        result.notes.append("service_notification_policy_missing")
        return

    policy = service.notification_policy
    result.policy_id = policy.id

    if policy.deleted:
        result.notes.append("service_notification_policy_deleted")
        return

    if not policy.enabled:
        result.notes.append("service_notification_policy_disabled")
        return

    if policy.team_id != getattr(group, "team_id", None):
        result.notes.append("service_notification_policy_team_mismatch")
        return

    matched = False
    rules = notification_policies_repo.list_policy_rules(
        policy.id,
        enabled_only=True,
    )

    for rule in rules:
        try:
            rule_matches = notification_rule_matches(group, rule, event_type)
        except Exception as exc:
            result.rule_errors.append({
                "rule_id": rule.id,
                "error": str(exc),
            })
            continue

        if not rule_matches:
            continue

        matched = True
        result.matched_rule_ids.append(rule.id)

        channels = notification_policies_repo.list_rule_channels(
            rule.id,
            enabled_only=True,
        )

        for channel in channels:
            _add_channel(result, channel, "service_policy", rule.id)

        if not rule.continue_matching:
            break

    if not matched:
        result.notes.append("no_matching_notification_policy_rule")


def resolve_notification_channels(group, event_type="notification"):
    """Resolve effective channels for one alert group event."""
    route = getattr(group, "route", None)
    policy_event_type = NOTIFICATION_POLICY_EVENT_ALIASES.get(event_type, event_type)

    if not route:
        result = NotificationChannelResolution(
            mode=SERVICE_POLICY,
            notes=["route_missing", "service_policy_without_route"],
        )

        _add_service_policy_channels(result, group, policy_event_type)

        if not result.channels:
            result.notes.append("no_channels_without_route")

        return result

    configured_mode = (
        getattr(route, "notification_channel_mode", None)
        or ROUTE_ONLY
    )

    if configured_mode in NOTIFICATION_CHANNEL_MODES:
        mode = configured_mode
    else:
        mode = ROUTE_ONLY

    result = NotificationChannelResolution(mode=mode)

    if configured_mode != mode:
        result.notes.append("unknown_channel_mode_fallback_to_route_only")

    if mode in {SERVICE_POLICY, SERVICE_POLICY_PLUS_ROUTE}:
        _add_service_policy_channels(result, group, policy_event_type)

    if mode in {ROUTE_ONLY, SERVICE_POLICY_PLUS_ROUTE}:
        _add_route_channels(result, route)

    return result
