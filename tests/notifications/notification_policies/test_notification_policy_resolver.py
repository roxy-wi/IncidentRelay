from app.services.notifications.policies.resolver import (
    resolve_notification_channels,
)
from tests.factories import (
    attach_channel,
    create_channel,
    create_group,
    create_impact_alert_group,
    create_notification_policy,
    create_notification_policy_rule,
    create_route,
    create_service,
    create_team,
)


def _channel_ids(resolution):
    return [channel.id for channel in resolution.channels]


def _create_group(team, route, service):
    return create_impact_alert_group(
        team=team,
        route=route,
        service=service,
        severity="critical",
    )


def test_route_only_uses_only_route_channels():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    route_channel = create_channel(group, team)
    policy_channel = create_channel(group, team)

    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        channels=[policy_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="route_only",
    )
    attach_channel(route, route_channel)

    alert_group = _create_group(team, route, service)
    resolution = resolve_notification_channels(alert_group)

    assert _channel_ids(resolution) == [route_channel.id]
    assert resolution.matched_rule_ids == []


def test_service_policy_uses_only_policy_channels():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    route_channel = create_channel(group, team)
    policy_channel = create_channel(group, team)

    policy = create_notification_policy(team)
    rule = create_notification_policy_rule(
        policy,
        channels=[policy_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )
    attach_channel(route, route_channel)

    alert_group = _create_group(team, route, service)
    resolution = resolve_notification_channels(alert_group)

    assert _channel_ids(resolution) == [policy_channel.id]
    assert resolution.matched_rule_ids == [rule.id]


def test_service_policy_plus_route_combines_and_deduplicates():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    shared_channel = create_channel(group, team)

    policy = create_notification_policy(team)
    rule = create_notification_policy_rule(
        policy,
        channels=[shared_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy_plus_route",
    )
    attach_channel(route, shared_channel)

    alert_group = _create_group(team, route, service)
    resolution = resolve_notification_channels(alert_group)

    assert _channel_ids(resolution) == [shared_channel.id]
    assert resolution.channel_sources[shared_channel.id] == [
        {
            "source": "service_policy",
            "rule_id": rule.id,
        },
        {
            "source": "route",
        },
    ]


def test_policy_matches_priority():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    p1_channel = create_channel(group, team)
    default_channel = create_channel(group, team)

    policy = create_notification_policy(team)
    p1_rule = create_notification_policy_rule(
        policy,
        position=1,
        matchers={"priority": ["p1", "p2"]},
        channels=[p1_channel],
    )
    create_notification_policy_rule(
        policy,
        position=2,
        matchers={},
        channels=[default_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    alert_group = _create_group(team, route, service)
    alert_group.priority_slug = "p1"
    alert_group.save()

    resolution = resolve_notification_channels(alert_group)

    assert _channel_ids(resolution) == [p1_channel.id]
    assert resolution.matched_rule_ids == [p1_rule.id]


def test_continue_matching_combines_policy_rules():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    critical_channel = create_channel(group, team)
    default_channel = create_channel(group, team)

    policy = create_notification_policy(team)
    critical_rule = create_notification_policy_rule(
        policy,
        position=1,
        matchers={"severity": "critical"},
        channels=[critical_channel],
        continue_matching=True,
    )
    default_rule = create_notification_policy_rule(
        policy,
        position=2,
        matchers={},
        channels=[default_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    alert_group = _create_group(team, route, service)
    resolution = resolve_notification_channels(alert_group)

    assert _channel_ids(resolution) == [
        critical_channel.id,
        default_channel.id,
    ]
    assert resolution.matched_rule_ids == [
        critical_rule.id,
        default_rule.id,
    ]


def test_policy_rule_filters_event_type():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    channel = create_channel(group, team)

    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        event_types=["notification"],
        channels=[channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    alert_group = _create_group(team, route, service)
    resolution = resolve_notification_channels(
        alert_group,
        event_type="reminder",
    )

    assert resolution.channels == []
    assert resolution.matched_rule_ids == []
    assert resolution.notes == ["no_matching_notification_policy_rule"]


def test_service_policy_without_policy_returns_no_channels():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    alert_group = _create_group(team, route, service)
    resolution = resolve_notification_channels(alert_group)

    assert resolution.channels == []
    assert resolution.notes == ["service_notification_policy_missing"]


def test_disabled_policy_channel_is_ignored():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    channel = create_channel(group, team)

    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        channels=[channel],
    )

    service.notification_policy = policy
    service.save()

    channel.enabled = False
    channel.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    alert_group = _create_group(team, route, service)
    resolution = resolve_notification_channels(alert_group)

    assert resolution.channels == []


def test_service_policy_matches_ui_operator_value_regex():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    database_channel = create_channel(group, team)
    default_channel = create_channel(group, team)

    policy = create_notification_policy(team)
    database_rule = create_notification_policy_rule(
        policy,
        position=1,
        matchers={
            "labels": {
                "Application": {
                    "op": "regex",
                    "value": "^(Listener|DB)$",
                }
            }
        },
        channels=[database_channel],
    )
    create_notification_policy_rule(
        policy,
        position=2,
        matchers={},
        channels=[default_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    alert_group = _create_group(team, route, service)
    labels = dict(alert_group.common_labels or {})
    labels["Application"] = "DB"
    alert_group.common_labels = labels
    alert_group.save()

    resolution = resolve_notification_channels(alert_group)

    assert _channel_ids(resolution) == [database_channel.id]
    assert resolution.matched_rule_ids == [database_rule.id]
