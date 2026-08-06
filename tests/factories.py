from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from app.login import hash_password
from app.modules.db import rotations_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertRoute,
    AlertRouteChannel,
    Group,
    NotificationChannel,
    Rotation,
    RotationOverride,
    Silence,
    Team,
    TeamUser,
    User,
    UserGroup,
    EscalationPolicy,
    EscalationPolicyRule,
    Service,
    ServiceDependency,
    NotificationPolicy,
    NotificationPolicyRule,
    NotificationPolicyRuleChannel,
    PriorityPolicy,
    PriorityPolicyRule,
    MatcherPreset,
    Heartbeat,
)
from app.modules.common import utc_now

_counter = 0


def unique(prefix: str) -> str:
    global _counter
    _counter += 1
    return f"{prefix}-{_counter}"


def create_group(name: str | None = None, slug: str | None = None) -> Group:
    name = name or unique("Group")
    slug = slug or unique("group")
    return Group.create(name=name, slug=slug, active=True)


_DEFAULT_EMAIL = object()


def create_user(
    username: str | None = None,
    group: Group | None = None,
    *,
    email: str | None | object = _DEFAULT_EMAIL,
    is_admin: bool = False,
    active: bool = True,
    group_role: str = "editor",
) -> User:
    username = username or unique("user")

    if email is _DEFAULT_EMAIL:
        email = f"{username}@example.com"

    user = User.create(
        username=username,
        display_name=username.title(),
        email=email,
        password_hash=hash_password("password-123"),
        active=active,
        is_admin=is_admin,
        active_group=group,
    )

    if group is not None:
        UserGroup.create(
            user=user,
            group=group,
            role=group_role,
            active=True,
        )

    return user


def create_team(group: Group, name: str | None = None, slug: str | None = None) -> Team:
    name = name or unique("Team")
    slug = slug or unique("team")
    return Team.create(group=group, name=name, slug=slug, active=True)


def add_user_to_team(team: Team, user: User, role: str = "manager") -> TeamUser:
    return TeamUser.create(team=team, user=user, role=role, active=True)


def local_naive_to_utc_naive(value: datetime, timezone_name: str | None = "UTC") -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(dt_timezone.utc).replace(tzinfo=None)

    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except Exception:
        zone = ZoneInfo("UTC")

    return value.replace(tzinfo=zone).astimezone(dt_timezone.utc).replace(tzinfo=None)


def create_rotation(
    team: Team,
    name: str | None = None,
    users: list[User] | None = None,
    *,
    start_at: datetime | None = None,
    duration_seconds: int = 86400,
    timezone: str = "UTC",
    handoff_time: str = "09:00",
) -> Rotation:
    rotation = rotations_repo.create_rotation(
        team_id=team.id,
        name=name or unique("Rotation"),
        description=None,
        start_at=start_at or utc_now().replace(microsecond=0),
        duration_seconds=duration_seconds,
        reminder_interval_seconds=300,
        rotation_type="daily",
        interval_value=1,
        interval_unit="days",
        handoff_time=handoff_time,
        timezone=timezone,
        handoff_weekday=None,
        enabled=True,
    )

    layer = rotations_repo.get_or_create_default_layer(rotation.id)

    member_starts_at = local_naive_to_utc_naive(
        layer.start_at or rotation.start_at,
        layer.timezone or rotation.timezone or timezone,
    )

    for index, user in enumerate(users or []):
        rotations_repo.add_rotation_layer_member(
            layer_id=layer.id,
            user_id=user.id,
            position=index,
            starts_at=member_starts_at,
        )

    return rotation


def create_rotation_override(
    rotation: Rotation,
    user: User,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> RotationOverride:
    starts_at = starts_at or utc_now() - timedelta(minutes=5)
    ends_at = ends_at or utc_now() + timedelta(minutes=5)
    return RotationOverride.create(
        rotation=rotation,
        user=user,
        starts_at=starts_at,
        ends_at=ends_at,
        reason="test override",
    )


def create_channel(
    group: Group,
    team: Team | None = None,
    *,
    channel_type: str = "webhook",
    config: dict | None = None,
) -> NotificationChannel:
    return NotificationChannel.create(
        group=group,
        team=team,
        name=unique("channel"),
        channel_type=channel_type,
        config=(
            {"webhook_url": ""}
            if config is None
            else config
        ),
        enabled=True,
    )


def create_route(
    team: Team,
    *,
    name: str | None = None,
    source: str = "alertmanager",
    token_hash: str | None = None,
    rotation: Rotation | None = None,
    escalation_policy=None,
    matchers: dict | None = None,
    group_by: list[str] | None = None,
    service: Service | None = None,
    integration_config: dict | None = None,
    notification_channel_mode: str = "route_only",
    matcher_preset: MatcherPreset | None = None,
) -> AlertRoute:
    return AlertRoute.create(
        team=team,
        rotation=rotation,
        escalation_policy=escalation_policy,
        matcher_preset=matcher_preset,
        name=name or unique("route"),
        source=source,
        enabled=True,
        matchers=matchers or {},
        group_by=group_by or [],
        intake_token_prefix="test-prefix" if token_hash else None,
        intake_token_hash=token_hash,
        service=service,
        integration_config=integration_config,
        notification_channel_mode=notification_channel_mode,
    )


def attach_channel(route: AlertRoute, channel: NotificationChannel) -> AlertRouteChannel:
    return AlertRouteChannel.create(route=route, channel=channel)


def create_alert(route: AlertRoute, *, status: str = "firing") -> Alert:
    return Alert.create(
        team=route.team,
        route=route,
        rotation=route.rotation,
        source=route.source,
        external_id=unique("external"),
        dedup_key=unique("dedup"),
        group_key=unique("group"),
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        labels={"alertname": "DiskFull", "instance": "host1", "team": route.team.slug},
        payload={"source": "test"},
        status=status,
    )


def create_silence(
    team: Team,
    *,
    matcher_preset: MatcherPreset | None = None,
    matchers: dict | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    apply_to_existing: bool = False,
    reactivate_on_end: bool = True,
) -> Silence:
    return Silence.create(
        team=team,
        name=unique("silence"),
        reason="test silence",
        matcher_preset=matcher_preset,
        matchers=matchers or {},
        starts_at=starts_at or utc_now() - timedelta(minutes=5),
        ends_at=ends_at or utc_now() + timedelta(minutes=5),
        apply_to_existing=apply_to_existing,
        reactivate_on_end=reactivate_on_end,
        enabled=True,
    )


def create_escalation_policy(
    team: Team,
    *,
    name: str | None = None,
    description: str | None = None,
    enabled: bool = True,
    repeat_count: int = 0,
) -> EscalationPolicy:
    return EscalationPolicy.create(
        team=team,
        name=name or unique("policy"),
        description=description,
        enabled=enabled,
        repeat_count=repeat_count,
    )


def create_escalation_policy_rule(
    policy: EscalationPolicy,
    *,
    position: int = 1,
    delay_seconds: int = 60,
    target_type: str = "rotation",
    rotation: Rotation | None = None,
    user: User | None = None,
    enabled: bool = True,
) -> EscalationPolicyRule:
    return EscalationPolicyRule.create(
        policy=policy,
        position=position,
        delay_seconds=delay_seconds,
        target_type=target_type,
        target_rotation=rotation if target_type == "rotation" else None,
        target_user=user if target_type == "user" else None,
        enabled=enabled,
    )


def create_service(
    team: Team,
    name: str | None = None,
    slug: str | None = None,
    *,
    service_type: str = "other",
    environment: str = "production",
    criticality: str = "medium",
    tier: str = "tier_3",
    status: str = "operational",
    enabled: bool = True,
) -> Service:
    service_name = name or unique("Service")
    service_slug = slug or unique("service")

    return Service.create(
        group=team.group,
        team=team,
        slug=service_slug,
        name=service_name,
        service_type=service_type,
        environment=environment,
        criticality=criticality,
        tier=tier,
        status=status,
        status_source="manual",
        labels={},
        tags=[],
        metadata={},
        enabled=enabled,
        public=False,
        public_order=100,
    )


def create_impact_alert_group(
    *,
    team,
    service,
    route=None,
    fingerprint=None,
    status="firing",
    severity="critical",
    alertname=None,
    summary=None,
    priority_slug=None,
    priority_order=None,
    priority_set_manually=False,
):
    now = utc_now()
    alertname = alertname or (service.slug + "-alert")
    summary = summary or (service.name + " alert")
    fingerprint = fingerprint or unique(service.slug + "-alert-group")

    labels = {
        "alertname": alertname,
        "severity": severity,
        "service": service.slug,
    }

    return AlertGroup.create(
        team=team,
        route=route,
        service=service,
        source="pytest",
        group_key_hash=fingerprint,
        group_key=fingerprint,
        title=alertname,
        message=summary,
        severity=severity,
        common_labels=labels,
        label_values=labels,
        payload_summary={
            "summary": summary,
            "alertname": alertname,
            "severity": severity,
        },
        status=status,
        first_seen_at=now,
        last_seen_at=now,
        alert_count=1,
        firing_count=1 if status == "firing" else 0,
        acknowledged_count=1 if status == "acknowledged" else 0,
        resolved_count=1 if status == "resolved" else 0,
        silenced_count=1 if status == "silenced" else 0,
        **(
            {
                "priority_slug": priority_slug,
                "priority_order": priority_order if priority_order is not None else 3,
                "priority_set_manually": priority_set_manually,
            }
            if priority_slug is not None
            else {}
        ),
    )


def create_service_alert(
    *,
    team,
    route,
    service,
    fingerprint,
    status="firing",
    severity="critical",
    alertname="TestAlert",
    summary="Test alert",
):
    labels = {
        "alertname": alertname,
        "severity": severity,
    }
    annotations = {
        "summary": summary,
    }

    return Alert.create(
        route=route,
        team=team,
        service=service,
        source=getattr(route, "source", None) or "alertmanager",
        external_id=fingerprint,
        dedup_key=fingerprint,
        group_key=fingerprint,
        title=summary,
        message=summary,
        severity=severity,
        labels=labels,
        payload={
            "status": status,
            "labels": labels,
            "annotations": annotations,
            "fingerprint": fingerprint,
        },
        status=status,
    )


def create_service_dependency(
    *,
    service,
    depends_on_service,
    dependency_type="hard",
    criticality="required",
    enabled=True,
):
    return ServiceDependency.create(
        service=service,
        depends_on_service=depends_on_service,
        dependency_type=dependency_type,
        criticality=criticality,
        enabled=enabled,
    )


def create_notification_policy(
    team: Team,
    *,
    name: str | None = None,
    description: str | None = None,
    enabled: bool = True,
) -> NotificationPolicy:
    return NotificationPolicy.create(
        team=team,
        name=name or unique("notification-policy"),
        description=description,
        enabled=enabled,
    )


def create_notification_policy_rule(
    policy: NotificationPolicy,
    *,
    name: str | None = None,
    position: int = 1,
    event_types: list[str] | None = None,
    matchers: dict | None = None,
    channels: list[NotificationChannel] | None = None,
    continue_matching: bool = False,
    enabled: bool = True,
    matcher_preset: MatcherPreset | None = None,
) -> NotificationPolicyRule:
    rule = NotificationPolicyRule.create(
        policy=policy,
        name=name or unique("notification-rule"),
        position=position,
        event_types=event_types or ["notification"],
        matchers=matchers or {},
        continue_matching=continue_matching,
        enabled=enabled,
        matcher_preset=matcher_preset,
    )

    for channel in channels or []:
        NotificationPolicyRuleChannel.create(
            rule=rule,
            channel=channel,
        )

    return rule


def create_priority_policy(
    team: Team,
    *,
    name: str | None = None,
    description: str | None = None,
    enabled: bool = True,
    default_for_team: bool = False,
    update_mode: str = "raise_only",
    source_priority_mode: str = "ignore",
    fallback_mode: str = "severity_mapping",
    fallback_priority=None,
) -> PriorityPolicy:
    return PriorityPolicy.create(
        team=team,
        name=name or unique("priority-policy"),
        description=description,
        enabled=enabled,
        default_for_team=default_for_team,
        update_mode=update_mode,
        source_priority_mode=source_priority_mode,
        fallback_mode=fallback_mode,
        fallback_priority=fallback_priority,
    )


def create_priority_policy_rule(
    policy: PriorityPolicy,
    priority,
    *,
    name: str | None = None,
    description: str | None = None,
    position: int = 1,
    matchers: dict | None = None,
    enabled: bool = True,
    matcher_preset: MatcherPreset | None = None,
) -> PriorityPolicyRule:
    return PriorityPolicyRule.create(
        policy=policy,
        name=name or unique("priority-rule"),
        description=description,
        position=position,
        matchers=matchers or {},
        priority=priority,
        enabled=enabled,
        matcher_preset=matcher_preset,
    )


def create_matcher_preset(
    team: Team,
    *,
    name: str | None = None,
    description: str | None = None,
    matchers: dict | None = None,
    enabled: bool = True,
) -> MatcherPreset:
    return MatcherPreset.create(
        team=team,
        name=name or unique("matcher-preset"),
        description=description,
        matchers=matchers or {},
        enabled=enabled,
    )


def create_heartbeat(
    team: Team,
    route: AlertRoute,
    *,
    service: Service | None = None,
    name: str | None = None,
    slug: str | None = None,
    token_hash: str = "heartbeat-token-hash",
    mode: str = "interval",
    expected_interval_seconds: int | None = 60,
    grace_period_seconds: int = 60,
    status: str = "new",
    last_seen_at: datetime | None = None,
    next_expected_at: datetime | None = None,
    schedule_kind: str | None = None,
    schedule_time: str | None = None,
    schedule_weekday: int | None = None,
    schedule_monthday: int | None = None,
    timezone: str = "UTC",
    severity: str = "critical",
    priority_slug: str = "p2",
    enabled: bool = True,
    auto_resolve: bool = True,
    instance_tracking_enabled: bool = False,
    instance_key: str = "instance",
    expected_instances_mode: str = "none",
    auto_discovery_ttl_days: int | None = None,
    labels: dict | None = None,
    metadata: dict | None = None,
) -> Heartbeat:
    return Heartbeat.create(
        group=team.group,
        team=team,
        route=route,
        service=service,
        name=name or unique("Heartbeat"),
        slug=slug or unique("heartbeat"),
        token_prefix="test-token",
        token_hash=token_hash,
        mode=mode,
        expected_interval_seconds=expected_interval_seconds,
        grace_period_seconds=grace_period_seconds,
        schedule_kind=schedule_kind,
        schedule_time=schedule_time,
        schedule_weekday=schedule_weekday,
        schedule_monthday=schedule_monthday,
        timezone=timezone,
        status=status,
        last_seen_at=last_seen_at,
        next_expected_at=next_expected_at,
        enabled=enabled,
        severity=severity,
        priority_slug=priority_slug,
        auto_resolve=auto_resolve,
        instance_tracking_enabled=instance_tracking_enabled,
        instance_key=instance_key,
        expected_instances_mode=expected_instances_mode,
        auto_discovery_ttl_days=auto_discovery_ttl_days,
        labels=labels or {},
        metadata=metadata or {},
    )

