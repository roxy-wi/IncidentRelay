import json
from datetime import datetime

from app.modules.sso.saml_security import get_saml_security
from app.modules.db import incidents_repo, maintenance_repo, services_repo
from app.modules.common import as_naive_datetime, as_utc_aware
from app.services.incidents.responder_display import responder_target_label


def extract_alert_event_link(alert):
    """Return external event/source link from alert labels."""
    labels = alert.labels or {}

    for key in (
        "event_link",
        "event_url",
        "alert_url",
        "source_url",
        "generator_url",
        "dashboard_url",
        "panel_url",
        "runbook_url",
    ):
        value = labels.get(key)

        if value:
            return value

    return None


def serialize_utc_datetime(value):
    """Serialize a datetime/string value as an explicit UTC ISO-8601 string."""
    value = as_utc_aware(value)

    if not value:
        return None

    return value.isoformat().replace("+00:00", "Z")


def serialize_local_datetime(value):
    """Serialize a local wall-clock datetime without timezone conversion."""
    value = as_naive_datetime(value)

    if not value:
        return None

    return value.isoformat()


def attach_group_permissions(data, group_id, current_user=None):
    """Attach group permissions to serialized data."""
    if current_user and group_id:
        from app.services.rbac import get_group_permissions

        data["permissions"] = get_group_permissions(current_user, group_id)

    return data


def attach_team_permissions(data, team_id, current_user=None):
    """Attach team permissions to serialized data."""
    if current_user and team_id:
        from app.services.rbac import get_team_permissions

        data["permissions"] = get_team_permissions(current_user, team_id)

    return data


def serialize_group(group, current_user=None):
    """
    Serialize a group.
    """

    data = {
        "id": group.id,
        "slug": group.slug,
        "name": group.name,
        "description": group.description,
        "active": group.active,
    }

    return attach_group_permissions(data, group.id, current_user)


def serialize_user_group(membership):
    """
    Serialize a group membership.
    """

    return {
        "id": membership.id,
        "group_id": membership.group.id,
        "group_slug": membership.group.slug,
        "group_name": membership.group.name,
        "role": membership.role,
        "active": membership.active,
    }


def serialize_team(team, current_user=None):
    """
    Serialize a team.
    """

    data = {
        "id": team.id,
        "group_id": team.group.id if team.group else None,
        "group_slug": team.group.slug if team.group else None,
        "group_name": team.group.name if team.group else None,
        "slug": team.slug,
        "name": team.name,
        "description": team.description,
        "escalation_enabled": team.escalation_enabled,
        "escalation_after_reminders": team.escalation_after_reminders,
        "active": team.active,
    }

    return attach_team_permissions(data, team.id, current_user)


def serialize_user(user, groups=None):
    """
    Serialize a user.
    """

    data = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "timezone": user.timezone,
        "telegram_user_id": user.telegram_user_id,
        "slack_user_id": user.slack_user_id,
        "mattermost_user_id": user.mattermost_user_id,
        "active": user.active,
        "is_admin": user.is_admin,
        "active_group_id": user.active_group.id if user.active_group else None,
        "active_group_slug": user.active_group.slug if user.active_group else None,
        "notify_oncall_shift_start_email": bool(
            getattr(user, "notify_oncall_shift_start_email", True)
        ),
        "notify_oncall_shift_end_email": bool(
            getattr(user, "notify_oncall_shift_end_email", True)
        ),
    }

    if groups is not None:
        data["groups"] = [serialize_profile_group(item) for item in groups]

    return data


def serialize_user_short(user):
    """
    Serialize a compact user object.
    """

    if not user:
        return None

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "telegram_user_id": user.telegram_user_id,
        "slack_user_id": user.slack_user_id,
        "mattermost_user_id": user.mattermost_user_id,
    }


def serialize_team_short(team):
    """Serialize a compact team object."""
    if not team:
        return None

    return {
        "id": team.id,
        "slug": team.slug,
        "name": team.name,
        "active": team.active,
        "group_id": team.group.id if team.group else None,
        "group_slug": team.group.slug if team.group else None,
    }


def serialize_rotation_short(rotation):
    """Serialize a compact rotation object."""
    if not rotation:
        return None

    team = rotation.team if getattr(rotation, "team_id", None) else None

    return {
        "id": rotation.id,
        "name": rotation.name,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "enabled": rotation.enabled,
        "timezone": rotation.timezone,
    }


def serialize_escalation_policy_short(policy):
    """Serialize a compact escalation policy object."""
    if not policy:
        return None

    team = policy.team if getattr(policy, "team_id", None) else None

    return {
        "id": policy.id,
        "name": policy.name,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "enabled": policy.enabled,
    }


def serialize_rotation(rotation, current_user=None, request_user=None):
    """Serialize a rotation.

    current_user is the current on-call user.
    request_user is the authenticated user used for permissions.
    """
    data = {
        "id": rotation.id,
        "team_id": rotation.team.id,
        "team_name": rotation.team.name,
        "team_slug": rotation.team.slug,
        "name": rotation.name,
        "description": rotation.description,
        "start_at": rotation.start_at.isoformat(),
        "duration_seconds": rotation.duration_seconds,
        "reminder_interval_seconds": rotation.reminder_interval_seconds,
        "rotation_type": rotation.rotation_type,
        "interval_value": rotation.interval_value,
        "interval_unit": rotation.interval_unit,
        "handoff_time": rotation.handoff_time,
        "handoff_weekday": rotation.handoff_weekday,
        "timezone": rotation.timezone,
        "enabled": rotation.enabled,
        "current_oncall": current_user.username if current_user else None,
    }

    return attach_team_permissions(data, rotation.team.id, request_user)


def serialize_channel(channel, current_user=None):
    """Serialize a notification channel."""
    team_id = channel.team.id if channel.team else None

    data = {
        "id": channel.id,
        "group_id": channel.group.id if getattr(channel, "group", None) else None,
        "group_name": channel.group.name if getattr(channel, "name", None) else None,
        "group_slug": channel.group.slug if getattr(channel, "group", None) else None,
        "team_id": team_id,
        "team_name": channel.team.name if channel.team else None,
        "team_slug": channel.team.slug if channel.team else None,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "config": channel.config,
        "enabled": channel.enabled,
    }

    data = attach_team_permissions(data, team_id, current_user)

    if current_user and team_id:
        from app.services.rbac import can_access_team_or_group_resource

        data.setdefault("permissions", {})["can_write"] = (
            can_access_team_or_group_resource(
                current_user,
                team_id,
                write_required=True,
            )
        )

    return data


def serialize_channel_short(channel):
    """
    Serialize a compact channel object.
    """

    if not channel:
        return None

    return {
        "id": channel.id,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "enabled": channel.enabled,
    }


def serialize_service_short(service):
    """Serialize a compact service object."""
    if not service:
        return None

    return {
        "id": service.id,
        "slug": service.slug,
        "name": service.name,
        "status": service.status,
        "criticality": service.criticality,
        "environment": service.environment,
        "enabled": service.enabled,
    }


def serialize_service_readiness_state(state):
    """Serialize the current aggregated service readiness state."""

    if state is None:
        return None

    return {
        "status": state.status,
        "score": state.score,
        "standards_count": state.standards_count,
        "checks_count": state.checks_count,
        "failed_count": state.failed_count,
        "failed_required_count": state.failed_required_count,
        "failed_critical_count": state.failed_critical_count,
        "batch_uid": str(state.batch_uid),
        "evaluated_at": serialize_utc_datetime(state.evaluated_at),
    }


def serialize_service_readiness_check_result(result):
    """Serialize one readiness check result snapshot."""

    return {
        "id": result.id,
        "check_id": result.check_id,
        "check_uid": str(result.check_uid) if result.check_uid else None,
        "check_slug": result.check_slug,
        "check_name": result.check_name,
        "check_type": result.check_type,
        "status": result.status,
        "weight": result.weight,
        "severity": result.severity,
        "required": result.required,
        "message": result.message,
        "details": result.details or {},
        "evaluated_at": serialize_utc_datetime(result.evaluated_at),
    }


def serialize_service_readiness_evaluation(evaluation, results=None):
    """Serialize one standard evaluation."""

    standard = evaluation.standard if evaluation.standard_id else None
    actor_user = evaluation.actor_user if evaluation.actor_user_id else None

    return {
        "id": evaluation.id,
        "uid": str(evaluation.uid),
        "batch_uid": str(evaluation.batch_uid),
        "service_id": evaluation.service_id,
        "standard": {
            "id": standard.id,
            "uid": str(standard.uid),
            "slug": standard.slug,
            "name": standard.name,
            "enabled": standard.enabled,
        } if standard else None,
        "status": evaluation.status,
        "score": evaluation.score,
        "passed_weight": evaluation.passed_weight,
        "total_weight": evaluation.total_weight,
        "checks_count": evaluation.checks_count,
        "failed_count": evaluation.failed_count,
        "failed_required_count": evaluation.failed_required_count,
        "failed_critical_count": evaluation.failed_critical_count,
        "trigger": evaluation.trigger,
        "actor_user_id": actor_user.id if actor_user else None,
        "evaluated_at": serialize_utc_datetime(evaluation.evaluated_at),
        "results": [
            serialize_service_readiness_check_result(result)
            for result in results or []
        ],
    }


def serialize_service_readiness(state, evaluations=None, results_by_evaluation=None):
    """Serialize the current readiness batch for a service."""

    results_by_evaluation = results_by_evaluation or {}

    return {
        "state": serialize_service_readiness_state(state),
        "evaluations": [
            serialize_service_readiness_evaluation(
                evaluation,
                results=results_by_evaluation.get(evaluation.id, []),
            )
            for evaluation in evaluations or []
        ],
    }


def serialize_service(service, current_user=None, readiness_state=None):
    """Serialize a service."""
    team = service.team if service.team_id else None
    group = service.group if service.group_id else None
    notification_policy = (
        service.notification_policy
        if getattr(service, "notification_policy_id", None)
        else None
    )

    priority_policy = (
        service.priority_policy
        if getattr(service, "priority_policy_id", None)
        else None
    )

    data = {
        "id": service.id,
        "uid": str(service.uid),
        "group_id": group.id if group else None,
        "group_slug": group.slug if group else None,
        "group_name": group.name if group else None,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,

        "slug": service.slug,
        "name": service.name,
        "description": service.description,
        "kind": service.kind,
        "lifecycle": service.lifecycle,

        "service_type": service.service_type,
        "environment": service.environment,
        "criticality": service.criticality,
        "tier": service.tier,

        "status": service.status,
        "status_source": service.status_source,
        "status_message": service.status_message,
        "status_updated_at": serialize_utc_datetime(service.status_updated_at),

        "default_rotation_id": (
            service.default_rotation.id
            if getattr(service, "default_rotation_id", None)
            else None
        ),
        "default_rotation_name": (
            service.default_rotation.name
            if getattr(service, "default_rotation_id", None)
            else None
        ),
        "default_escalation_policy_id": (
            service.default_escalation_policy.id
            if getattr(service, "default_escalation_policy_id", None)
            else None
        ),
        "default_escalation_policy_name": (
            service.default_escalation_policy.name
            if getattr(service, "default_escalation_policy_id", None)
            else None
        ),

        "notification_policy_id": (
            notification_policy.id if notification_policy else None
        ),
        "notification_policy_name": (
            notification_policy.name if notification_policy else None
        ),
        "priority_policy_id": (
            priority_policy.id if priority_policy else None
        ),
        "priority_policy_name": (
            priority_policy.name if priority_policy else None
        ),

        "labels": service.labels or {},
        "tags": service.tags or [],
        "metadata": service.metadata or {},

        "enabled": service.enabled,
        "public": service.public,
        "public_name": service.public_name,
        "public_description": service.public_description,
        "public_order": service.public_order,

        "created_at": serialize_utc_datetime(service.created_at),
        "updated_at": serialize_utc_datetime(service.updated_at),
        "readiness": serialize_service_readiness_state(readiness_state),
        "active_maintenance": serialize_active_maintenance_for_scope(
            group_id=service.team.group_id if service.team_id and service.team else None,
            team_id=service.team_id,
            service_id=service.id,
        ),
        "owners": [
            serialize_service_owner(owner, current_user)
            for owner in services_repo.list_service_owners(
                service.id,
                active_only=True,
            )
        ],
    }

    return attach_team_permissions(data, service.team_id, current_user)


def serialize_service_standard_check(check):
    """Serialize a service readiness standard check."""

    return {
        "id": check.id,
        "uid": str(check.uid),
        "standard_id": check.standard_id,
        "slug": check.slug,
        "name": check.name,
        "description": check.description,
        "check_type": check.check_type,
        "configuration": check.configuration or {},
        "weight": check.weight,
        "severity": check.severity,
        "required": check.required,
        "enabled": check.enabled,
        "position": check.position,
        "created_at": serialize_utc_datetime(check.created_at),
        "updated_at": serialize_utc_datetime(check.updated_at),
    }


def serialize_service_standard(standard, current_user=None, checks=None):
    """Serialize a service readiness standard."""

    group = standard.group if standard.group_id else None
    created_by = standard.created_by if standard.created_by_id else None

    data = {
        "id": standard.id,
        "uid": str(standard.uid),
        "group_id": group.id if group else None,
        "group_slug": group.slug if group else None,
        "group_name": group.name if group else None,
        "slug": standard.slug,
        "name": standard.name,
        "description": standard.description,
        "applies_to": standard.applies_to or {},
        "enabled": standard.enabled,
        "created_by": serialize_user_short(created_by),
        "created_at": serialize_utc_datetime(standard.created_at),
        "updated_at": serialize_utc_datetime(standard.updated_at),
    }

    if checks is not None:
        data["checks"] = [serialize_service_standard_check(check) for check in checks]
        data["checks_count"] = len(checks)

    return attach_group_permissions(data, standard.group_id, current_user)


def serialize_service_match_rule(rule, current_user=None):
    """Serialize a service match rule."""
    service = rule.service if rule.service_id else None
    route = rule.route if getattr(rule, "route_id", None) else None
    team = rule.team if rule.team_id else None
    matcher_preset = (
        rule.matcher_preset
        if getattr(rule, "matcher_preset_id", None)
        else None
    )

    data = {
        "id": rule.id,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,

        "route_id": route.id if route else None,
        "route_name": route.name if route else None,

        "service_id": service.id if service else None,
        "service_slug": service.slug if service else None,
        "service_name": service.name if service else None,

        "position": rule.position,
        "name": rule.name,
        "description": rule.description,
        "matcher_preset_id": matcher_preset.id if matcher_preset else None,
        "matcher_preset": {
            "id": matcher_preset.id,
            "name": matcher_preset.name,
            "version": matcher_preset.version,
            "enabled": matcher_preset.enabled,
        } if matcher_preset else None,
        "matchers": rule.matchers or {},
        "enabled": rule.enabled,

        "created_at": serialize_utc_datetime(rule.created_at),
        "updated_at": serialize_utc_datetime(rule.updated_at),
    }

    return attach_team_permissions(data, rule.team_id, current_user)


def serialize_route_integration_config(route):
    """Serialize provider-specific integration config without secrets."""
    config = route.integration_config or {}

    if route.source == "sentry":
        sentry = dict(
            config.get("sentry") or {}
        )

        return {
            "sentry": {
                "has_webhook_secret": bool(
                    sentry.get("webhook_secret")
                ),
                "webhook_path": (
                    f"/api/integrations/sentry/{route.id}"
                ),
            }
        }

    if route.source == "aws_sns":
        aws_sns = dict(
            config.get("aws_sns") or {}
        )

        return {
            "aws_sns": {
                "topic_arn": aws_sns.get(
                    "topic_arn"
                ),
                "webhook_path": (
                    f"/api/integrations/aws-sns/{route.id}"
                ),
            }
        }

    return {}


def serialize_route(route, current_user=None):
    """
    Serialize an alert route.
    """

    channels = [serialize_channel_short(link.channel) for link in route.route_channels]
    matcher_preset = (
        route.matcher_preset
        if getattr(route, "matcher_preset_id", None)
        else None
    )

    data = {
        "id": route.id,
        "team_id": route.team.id,
        "team_name": route.team.name,
        "team_slug": route.team.slug,
        "name": route.name,
        "source": route.source,
        "rotation_id": route.rotation.id if route.rotation else None,
        "rotation_name": route.rotation.name if route.rotation else None,
        "escalation_policy_id": route.escalation_policy.id if route.escalation_policy else None,
        "escalation_policy_name": route.escalation_policy.name if route.escalation_policy else None,
        "escalation_mode": "policy" if route.escalation_policy else "rotation",
        "team_escalation_enabled": route.team.escalation_enabled if route.team else None,
        "team_escalation_after_reminders": (
            route.team.escalation_after_reminders if route.team else None
        ),
        "matcher_preset_id": matcher_preset.id if matcher_preset else None,
        "matcher_preset": {
            "id": matcher_preset.id,
            "name": matcher_preset.name,
            "version": matcher_preset.version,
            "enabled": matcher_preset.enabled,
        } if matcher_preset else None,
        "matchers": route.matchers,
        "group_by": route.group_by,
        "integration_config": serialize_route_integration_config(route),
        "notification_channel_mode": route.notification_channel_mode or "route_only",
        "enabled": route.enabled,
        "intake_token_prefix": route.intake_token_prefix,
        "has_intake_token": bool(route.intake_token_hash),
        "channels": channels,
        "service_id": route.service.id if getattr(route, "service_id", None) else None,
        "service_name": route.service.name if getattr(route, "service_id", None) else None,
        "service_slug": route.service.slug if getattr(route, "service_id", None) else None,
        "active_maintenance": serialize_active_maintenance_for_scope(
            group_id=route.team.group_id if route.team_id and route.team else None,
            team_id=route.team_id,
            service_id=route.service_id,
            route_id=route.id,
        ),
    }

    return attach_team_permissions(data, route.team.id, current_user)


def serialize_alert_event(event):
    """
    Serialize an alert event.
    """

    return {
        "id": event.id,
        "event_type": event.event_type,
        "message": event.message,
        "user": serialize_user_short(event.user),
        "created_at": event.created_at.isoformat(),
    }


def serialize_alert_notification(notification):
    """Serialize an alert notification delivery record."""
    channel = notification.channel
    config = channel.config or {}

    return {
        "id": notification.id,
        "channel": serialize_channel_short(channel),
        "provider": notification.provider,
        "configured_channel_id": config.get("channel_id") if channel.channel_type == "mattermost" else None,
        "external_message_id": notification.external_message_id,
        "external_channel_id": notification.external_channel_id,
        "provider_payload": notification.provider_payload or {},
        "last_event_type": notification.last_event_type,
        "last_error": notification.last_error,
        "created_at": notification.created_at.isoformat(),
        "updated_at": notification.updated_at.isoformat(),
    }


def serialize_alert(
    alert,
    include_payload=False,
    current_user=None,
):
    """
    Serialize an alert.
    """

    team = alert.team
    route = alert.route
    rotation = alert.rotation
    service = alert.service if getattr(alert, "service_id", None) else None
    escalation_policy = (
        alert.escalation_policy
        if getattr(alert, "escalation_policy_id", None)
        else None
    )
    escalation_rule = (
        alert.escalation_rule
        if getattr(alert, "escalation_rule_id", None)
        else None
    )

    data = {
        "id": alert.id,
        "type": "alert",
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "route_id": route.id if route else None,
        "route_name": route.name if route else None,
        "route_source": route.source if route else None,
        "rotation_id": rotation.id if rotation else None,
        "rotation_name": rotation.name if rotation else None,
        "rotation_reminder_interval_seconds": rotation.reminder_interval_seconds if rotation else None,
        "source": alert.source,
        "external_id": alert.external_id,
        "dedup_key": alert.dedup_key,
        "group_key": alert.group_key,
        "title": alert.title,
        "message": alert.message,
        "severity": alert.severity,
        "status": alert.status,
        "previous_status": alert.previous_status,
        "silenced": alert.silenced,
        "labels": alert.labels or {},
        "labels_count": len(alert.labels or {}),
        "event_link": extract_alert_event_link(alert),
        "assignee": alert.assignee.username if alert.assignee else None,
        "assignee_id": alert.assignee.id if alert.assignee else None,
        "assignee_details": serialize_user_short(alert.assignee),
        "acknowledged_by": alert.acknowledged_by.username if alert.acknowledged_by else None,
        "acknowledged_by_details": serialize_user_short(alert.acknowledged_by),
        "acknowledged_at": serialize_utc_datetime(alert.acknowledged_at),
        "first_seen_at": serialize_utc_datetime(alert.first_seen_at),
        "last_seen_at": serialize_utc_datetime(alert.last_seen_at),
        "last_notification_at": serialize_utc_datetime(alert.last_notification_at),
        "reminder_count": alert.reminder_count,
        "escalation_level": alert.escalation_level,
        "escalation_mode": "policy" if escalation_policy else "rotation",
        "escalation_policy_id": escalation_policy.id if escalation_policy else None,
        "escalation_policy_name": escalation_policy.name if escalation_policy else None,
        "escalation_rule_id": escalation_rule.id if escalation_rule else None,
        "escalation_rule_position": escalation_rule.position if escalation_rule else None,
        "escalation_rule_target_type": escalation_rule.target_type if escalation_rule else None,
        "next_escalation_at": serialize_utc_datetime(getattr(alert, "next_escalation_at", None)),
        "last_escalated_at": serialize_utc_datetime(getattr(alert, "last_escalated_at", None)),
        "escalation_repeat_count": getattr(alert, "escalation_repeat_count", 0),
        "team_escalation_enabled": team.escalation_enabled if team else None,
        "team_escalation_after_reminders": (team.escalation_after_reminders if team else None),
        "resolved_at": serialize_utc_datetime(alert.resolved_at),
        "service_id": service.id if service else None,
        "service_slug": service.slug if service else None,
        "service_name": service.name if service else None,
        "service_status": service.status if service else None,
        "service_criticality": service.criticality if service else None,
        "service_environment": service.environment if service else None,
        "service": serialize_service_short(service),
        "service_tier": service.tier if service else None,
    }

    if route:
        data["route"] = {
            "id": route.id,
            "name": route.name,
            "source": route.source,
            "matchers": route.matchers,
            "group_by": route.group_by,
            "enabled": route.enabled,
        }
        data["route"]["escalation_policy_id"] = (
            route.escalation_policy.id if getattr(route, "escalation_policy_id", None) else None
        )
        data["route"]["escalation_policy_name"] = (
            route.escalation_policy.name if getattr(route, "escalation_policy_id", None) else None
        )
        data["route"]["escalation_mode"] = (
            "policy" if getattr(route, "escalation_policy_id", None) else "rotation"
        )
        data["route"]["service_id"] = (
            route.service.id if getattr(route, "service_id", None) else None
        )
        data["route"]["service_name"] = (
            route.service.name if getattr(route, "service_id", None) else None
        )
        data["route"]["service_slug"] = (
            route.service.slug if getattr(route, "service_id", None) else None
        )

    if service:
        data["service"] = {
            "id": service.id,
            "name": service.name,
            "slug": service.slug,
            "status": service.status,
            "criticality": service.criticality,
            "environment": service.environment,
            "tier": service.tier,
            "enabled": service.enabled,
            "team_id": service.team.id if service.team else None,
            "team_slug": service.team.slug if service.team else None,
            "team_name": service.team.name if service.team else None,
        }

    if rotation:
        data["rotation"] = {
            "id": rotation.id,
            "name": rotation.name,
            "duration_seconds": rotation.duration_seconds,
            "reminder_interval_seconds": rotation.reminder_interval_seconds,
            "rotation_type": rotation.rotation_type,
            "interval_value": rotation.interval_value,
            "interval_unit": rotation.interval_unit,
            "handoff_time": rotation.handoff_time,
            "timezone": rotation.timezone,
            "enabled": rotation.enabled,
        }

    if include_payload:
        data["payload"] = alert.payload

    return attach_team_permissions(data, team.id if team else None, current_user)


def serialize_api_token(token):
    """
    Serialize API token metadata.

    Never expose token_hash or full raw token.
    """
    expires_at = token.expires_at
    expired = bool(expires_at and expires_at <= datetime.utcnow())

    return {
        "id": token.id,
        "name": token.name,
        "token_prefix": token.token_prefix,
        "scopes": token.scopes or [],
        "group_id": token.group.id if token.group else None,
        "group_slug": token.group.slug if token.group else None,
        "group_name": token.group.name if token.group else None,
        "team_id": token.team.id if token.team else None,
        "team_slug": token.team.slug if token.team else None,
        "active": token.active,
        "expired": expired,
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
    }


def serialize_profile_group(item):
    """Serialize a real UserGroup membership or a synthetic profile group."""
    if isinstance(item, dict):
        return item

    return serialize_user_group(item)


def serialize_rotation_layer(layer, current_user=None):
    """Serialize a rotation layer."""
    team_id = layer.rotation.team.id

    data = {
        "id": layer.id,
        "rotation_id": layer.rotation.id,
        "team_id": team_id,
        "name": layer.name,
        "description": layer.description,
        "priority": layer.priority,
        "start_at": layer.start_at.isoformat() if layer.start_at else None,
        "duration_seconds": layer.duration_seconds,
        "rotation_type": layer.rotation_type,
        "interval_value": layer.interval_value,
        "interval_unit": layer.interval_unit,
        "handoff_time": layer.handoff_time,
        "handoff_weekday": layer.handoff_weekday,
        "timezone": layer.timezone,
        "enabled": layer.enabled,
        "deleted": layer.deleted,
    }

    return attach_team_permissions(data, team_id, current_user)


def serialize_rotation_layer_member(member):
    """Serialize a rotation layer member."""
    return {
        "id": member.id,
        "layer_id": member.layer.id,
        "user_id": member.user.id,
        "username": member.user.username,
        "display_name": member.user.display_name,
        "position": member.position,
        "active": member.active,
        "starts_at": serialize_utc_datetime(member.starts_at),
        "ends_at": serialize_utc_datetime(member.ends_at),
    }


def serialize_rotation_layer_restriction(item):
    """Serialize a rotation layer restriction."""
    return {
        "id": item.id,
        "layer_id": item.layer.id,
        "weekday": item.weekday,
        "start_time": item.start_time,
        "end_time": item.end_time,
    }


def serialize_sso_provider(provider):
    """Serialize SSO provider without secrets."""
    return {
        "id": provider.id,
        "slug": provider.slug,
        "label": provider.label,
        "protocol": provider.protocol,
        "enabled": provider.enabled,

        "subject_claim": provider.subject_claim,
        "email_claim": provider.email_claim,
        "username_claim": provider.username_claim,
        "display_name_claim": provider.display_name_claim,
        "groups_claim": provider.groups_claim,
        "phone_claim": provider.phone_claim,

        "allowed_domains": provider.allowed_domains or [],

        "auto_create_users": provider.auto_create_users,
        "auto_link_by_email": provider.auto_link_by_email,
        "require_verified_email": provider.require_verified_email,

        "sync_group_memberships": provider.sync_group_memberships,
        "remove_missing_group_memberships": provider.remove_missing_group_memberships,

        "client_id": provider.client_id,
        "has_client_secret": bool(provider.client_secret_encrypted),

        "oidc_metadata_url": provider.oidc_metadata_url,
        "oidc_issuer": provider.oidc_issuer,
        "oidc_authorization_endpoint": provider.oidc_authorization_endpoint,
        "oidc_token_endpoint": provider.oidc_token_endpoint,
        "oidc_userinfo_endpoint": provider.oidc_userinfo_endpoint,
        "oidc_jwks_uri": provider.oidc_jwks_uri,
        "oidc_scope": provider.oidc_scope,

        "saml_idp_entity_id": provider.saml_idp_entity_id,
        "saml_idp_sso_url": provider.saml_idp_sso_url,
        "saml_idp_slo_url": provider.saml_idp_slo_url,
        "saml_idp_x509_cert": provider.saml_idp_x509_cert,
        "saml_idp_metadata_url": provider.saml_idp_metadata_url,

        "saml_sp_entity_id": provider.saml_sp_entity_id,
        "saml_sp_acs_url": provider.saml_sp_acs_url,
        "saml_sp_sls_url": provider.saml_sp_sls_url,
        "saml_sp_x509_cert": provider.saml_sp_x509_cert,
        "has_saml_sp_private_key": bool(provider.saml_sp_private_key_encrypted),
        "saml_name_id_format": provider.saml_name_id_format,

        "extra_config": provider.extra_config or {},
        "saml_security": get_saml_security(provider.extra_config),

        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


def serialize_sso_group_mapping(mapping):
    """Serialize SSO group mapping."""
    group = mapping.incidentrelay_group

    return {
        "id": mapping.id,
        "provider_id": mapping.provider.id,
        "external_group": mapping.external_group,
        "group_id": group.id,
        "group_slug": group.slug,
        "group_name": group.name,
        "group_role": mapping.group_role,
        "active": mapping.active,
        "priority": mapping.priority,
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None,
    }


def serialize_service_link(link, current_user=None):
    """Serialize a service link."""
    service = link.service
    team = service.team if service else None

    data = {
        "id": link.id,

        "service_id": service.id if service else link.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,

        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,

        "link_type": link.link_type,
        "label": link.label,
        "url": link.url,
        "description": link.description,
        "priority": link.priority,
        "enabled": link.enabled,
        "created_at": serialize_utc_datetime(link.created_at),
        "updated_at": serialize_utc_datetime(link.updated_at),
    }

    return attach_team_permissions(
        data,
        team.id if team else None,
        current_user,
    )


def serialize_service_owner(owner, current_user=None):
    """Serialize a service owner."""
    service = owner.service
    user = owner.user

    return {
        "id": owner.id,
        "service_id": service.id if service else None,
        "team_id": service.team_id if service else None,
        "group_id": service.group_id if service else None,
        "user_id": user.id if user else None,
        "username": user.username if user else None,
        "user_email": user.email if user else None,
        "user_display_name": getattr(user, "display_name", None)
        if user
        else None,
        "role": owner.role,
        "active": owner.active,
        "notify_on_created": bool(getattr(owner, "notify_on_created", True)),
        "notify_on_priority_change": bool(getattr(owner, "notify_on_priority_change", True)),
        "notify_on_status_change": bool(getattr(owner, "notify_on_status_change", True)),
        "notify_on_resolved": bool(getattr(owner, "notify_on_resolved", True)),
        "notify_on_comment": bool(getattr(owner, "notify_on_comment", True)),
        "created_at": owner.created_at.isoformat()
        if owner.created_at
        else None,
    }


def serialize_service_runbook(runbook, current_user=None):
    """Serialize a service runbook."""
    service = runbook.service
    team = service.team if service else None
    matcher_preset = (
        runbook.matcher_preset
        if getattr(runbook, "matcher_preset_id", None)
        else None
    )

    data = {
        "id": runbook.id,

        "service_id": service.id if service else runbook.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,

        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,

        "title": runbook.title,
        "description": runbook.description,
        "url": runbook.url,
        "severity": runbook.severity,
        "matcher_preset_id": matcher_preset.id if matcher_preset else None,
        "matcher_preset": {
            "id": matcher_preset.id,
            "name": matcher_preset.name,
            "version": matcher_preset.version,
            "enabled": matcher_preset.enabled,
            "matchers": matcher_preset.matchers or {},
        } if matcher_preset else None,
        "matchers": runbook.matchers or {},
        "priority": runbook.priority,
        "enabled": runbook.enabled,
        "created_at": serialize_utc_datetime(runbook.created_at),
        "updated_at": serialize_utc_datetime(runbook.updated_at),
    }

    return attach_team_permissions(
        data,
        team.id if team else None,
        current_user,
    )



def serialize_service_slo(slo, current_user=None, evaluation=None):
    """Serialize a service objective / SLO target."""
    service = slo.service if getattr(slo, "service_id", None) else None
    team = service.team if service and getattr(service, "team_id", None) else None

    data = {
        "id": slo.id,
        "service_id": service.id if service else slo.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,
        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,
        "name": slo.name,
        "description": slo.description,
        "severity": slo.severity,
        "ack_target_seconds": slo.ack_target_seconds,
        "resolve_target_seconds": slo.resolve_target_seconds,
        "availability_target_basis_points": slo.availability_target_basis_points,
        "enabled": slo.enabled,
        "created_at": serialize_utc_datetime(slo.created_at),
        "updated_at": serialize_utc_datetime(slo.updated_at),
    }

    if evaluation is not None:
        data["evaluation"] = evaluation

    return attach_team_permissions(
        data,
        team.id if team else None,
        current_user,
    )

def serialize_service_dependency(dependency, current_user=None):
    """Serialize a service dependency."""
    service = dependency.service
    depends_on = dependency.depends_on_service

    data = {
        "id": dependency.id,

        "service_id": service.id,
        "service_name": service.name,
        "service_slug": service.slug,
        "team_id": service.team.id if service.team else None,
        "team_name": service.team.name if service.team else None,
        "team_slug": service.team.slug if service.team else None,

        "depends_on_service_id": depends_on.id,
        "depends_on_service_name": depends_on.name,
        "depends_on_service_slug": depends_on.slug,
        "depends_on_service_status": depends_on.status,

        "depends_on_team_id": depends_on.team.id if depends_on.team else None,
        "depends_on_team_name": depends_on.team.name if depends_on.team else None,
        "depends_on_team_slug": depends_on.team.slug if depends_on.team else None,

        "dependency_type": dependency.dependency_type,
        "criticality": dependency.criticality,
        "description": dependency.description,
        "enabled": dependency.enabled,
        "created_at": serialize_utc_datetime(dependency.created_at),
        "updated_at": serialize_utc_datetime(dependency.updated_at),
    }

    return attach_team_permissions(data, service.team_id, current_user)


def serialize_incident_responder_target(responder):
    """Serialize responder target as one consistent object."""
    target_type = responder.target_type
    label = responder_target_label(responder)

    if target_type == "user":
        user = responder.target_user if responder.target_user_id else None
        return {
            "type": "user",
            "id": responder.target_user_id,
            "label": label,
            "user": serialize_user_short(user),
        }

    if target_type == "team":
        team = responder.target_team if responder.target_team_id else None
        return {
            "type": "team",
            "id": responder.target_team_id,
            "label": label,
            "team": serialize_team_short(team),
        }

    if target_type == "rotation":
        rotation = (
            responder.target_rotation
            if responder.target_rotation_id
            else None
        )
        return {
            "type": "rotation",
            "id": responder.target_rotation_id,
            "label": label,
            "rotation": serialize_rotation_short(rotation),
        }

    if target_type == "escalation_policy":
        policy = (
            responder.target_escalation_policy
            if responder.target_escalation_policy_id
            else None
        )
        return {
            "type": "escalation_policy",
            "id": responder.target_escalation_policy_id,
            "label": label,
            "escalation_policy": serialize_escalation_policy_short(policy),
        }

    return {
        "type": target_type,
        "id": None,
        "label": label,
    }


def serialize_incident_responder(responder):
    """Serialize incident responder request."""
    return {
        "id": responder.id,
        "incident_id": responder.group_id,
        "group_id": responder.group_id,

        "target_type": responder.target_type,
        "target_user_id": responder.target_user_id,
        "target_team_id": responder.target_team_id,
        "target_rotation_id": responder.target_rotation_id,
        "target_escalation_policy_id": (
            responder.target_escalation_policy_id
        ),
        "target": serialize_incident_responder_target(responder),

        "requested_by_id": responder.requested_by_id,
        "requested_by": serialize_user_short(
            responder.requested_by
            if responder.requested_by_id
            else None
        ),

        "accepted_by_id": responder.accepted_by_id,
        "accepted_by": serialize_user_short(
            responder.accepted_by
            if responder.accepted_by_id
            else None
        ),

        "declined_by_id": responder.declined_by_id,
        "declined_by": serialize_user_short(
            responder.declined_by
            if responder.declined_by_id
            else None
        ),

        "status": responder.status,
        "message": responder.message,
        "response_message": responder.response_message,

        "notification_status": responder.notification_status,
        "notification_error": responder.notification_error,

        "requested_at": serialize_utc_datetime(responder.requested_at),
        "responded_at": serialize_utc_datetime(responder.responded_at),
        "expires_at": serialize_utc_datetime(responder.expires_at),
        "created_at": serialize_utc_datetime(responder.created_at),
        "updated_at": serialize_utc_datetime(responder.updated_at),
    }


def serialize_incident_priority(priority):
    """Serialize incident priority object."""
    if not priority:
        return None

    return {
        "id": priority.id,
        "slug": priority.slug,
        "name": priority.name,
        "description": priority.description,
        "level": priority.level,
        "color": priority.color,
        "enabled": priority.enabled,
        "default": priority.default,
    }


def serialize_priority_ref(obj):
    """Serialize priority fields from AlertGroup or Alert without returning ORM object."""
    priority = None

    if getattr(obj, "priority_id", None):
        try:
            priority = obj.priority
        except Exception:
            priority = None

    slug = (
        getattr(obj, "priority_slug", None)
        or getattr(priority, "slug", None)
        or "p3"
    )

    order = (
        getattr(obj, "priority_order", None)
        or getattr(priority, "level", None)
        or 3
    )

    return {
        "priority": slug,
        "priority_id": getattr(obj, "priority_id", None),
        "priority_slug": slug,
        "priority_order": order,
        "priority_details": serialize_incident_priority(priority),
    }


def serialize_alert_group(
    group,
    include_payload=False,
    include_details=False,
    alerts=None,
    events=None,
    notifications=None,
    responders=None,
    current_user=None,
):
    """Serialize an alert group as the primary incident object."""

    team = group.team if getattr(group, "team_id", None) else None
    route = group.route if getattr(group, "route_id", None) else None
    rotation = group.rotation if getattr(group, "rotation_id", None) else None
    service = group.service if getattr(group, "service_id", None) else None

    data = {
        "id": group.id,
        "type": "alert_group",

        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,

        "route_id": route.id if route else None,
        "route_name": route.name if route else None,
        "route_source": route.source if route else None,

        "service_id": service.id if service else None,
        "service_slug": service.slug if service else None,
        "service_name": service.name if service else None,

        "rotation_id": rotation.id if rotation else None,
        "rotation_name": rotation.name if rotation else None,

        "source": group.source,
        "group_key": group.group_key,
        "group_key_hash": group.group_key_hash,

        "title": group.title,
        "message": group.message,
        "severity": group.severity,
        "status": group.status,
        "previous_status": group.previous_status,
        "silenced": bool(group.silenced),

        "common_labels": group.common_labels or {},
        "label_values": group.label_values or {},
        "labels": group.common_labels or {},
        "labels_count": len(group.common_labels or {}),

        "alert_count": group.alert_count,
        "firing_count": group.firing_count,
        "acknowledged_count": group.acknowledged_count,
        "resolved_count": group.resolved_count,
        "silenced_count": group.silenced_count,

        "assignee": group.assignee.username if group.assignee else None,
        "assignee_id": group.assignee.id if group.assignee else None,
        "assignee_details": serialize_user_short(group.assignee),

        "acknowledged_by": (
            group.acknowledged_by.username if group.acknowledged_by else None
        ),
        "acknowledged_by_details": serialize_user_short(group.acknowledged_by),
        "acknowledged_at": serialize_utc_datetime(group.acknowledged_at),

        "resolved_by": group.resolved_by.username if group.resolved_by else None,
        "resolved_by_details": serialize_user_short(group.resolved_by),
        "resolved_at": serialize_utc_datetime(group.resolved_at),

        "first_seen_at": serialize_utc_datetime(group.first_seen_at),
        "last_seen_at": serialize_utc_datetime(group.last_seen_at),
        "last_notification_at": serialize_utc_datetime(group.last_notification_at),

        "reminder_count": group.reminder_count,

        "escalation_level": group.escalation_level,
        "next_escalation_at": serialize_utc_datetime(group.next_escalation_at),
        "last_escalated_at": serialize_utc_datetime(group.last_escalated_at),
        "escalation_repeat_count": group.escalation_repeat_count,

        "merged_into_id": group.merged_into.id if group.merged_into else None,
        "merged_at": serialize_utc_datetime(group.merged_at),
        "merge_reason": group.merge_reason,
        "escalation_mode": "policy" if group.escalation_policy_id else "rotation",
        "escalation_policy_id": group.escalation_policy_id,
        "escalation_policy_name": group.escalation_policy.name if group.escalation_policy else None,
        "escalation_rule_id": group.escalation_rule_id,
        "escalation_rule_position": group.escalation_rule.position if group.escalation_rule else None,
        "escalation_rule_target_type": group.escalation_rule.target_type if group.escalation_rule else None,
        "team_escalation_enabled": group.team.escalation_enabled if group.team else None,
        "maintenance_window_id": group.maintenance_window_id,
        "maintenance_suppressed": group.maintenance_suppressed,
    }

    data.update(serialize_priority_ref(group))

    if include_payload:
        data["payload_summary"] = group.payload_summary

    if include_details:
        data["alerts"] = [
            serialize_alert(alert, current_user=current_user)
            for alert in alerts or []
        ]
        data["events"] = [
            serialize_alert_event(event)
            for event in events or []
        ]
        data["notifications"] = [
            serialize_alert_notification(notification)
            for notification in notifications or []
        ]
        if responders is None:
            responders = incidents_repo.list_incident_responders(group.id)

        data["responders"] = [
            serialize_incident_responder(item)
            for item in responders
        ]

    data["active_maintenance"] = serialize_attached_maintenance_ref(group)

    return attach_team_permissions(data, team.id if team else None, current_user)


def serialize_alert_comment(comment):
    user = comment.user if getattr(comment, "user_id", None) else None

    created_at = comment.created_at.isoformat() if comment.created_at else None
    updated_at = comment.updated_at.isoformat() if comment.updated_at else None

    return {
        "id": comment.id,
        "group_id": comment.group_id,
        "alert_id": comment.alert_id,
        "user_id": comment.user_id,
        "user": {
            "id": user.id,
            "username": getattr(user, "username", None),
            "email": getattr(user, "email", None),
            "display_name": getattr(user, "display_name", None),
        } if user else None,
        "body": comment.body,
        "created_at": created_at,
        "updated_at": updated_at,
        "edited": bool(
            comment.created_at
            and comment.updated_at
            and comment.updated_at > comment.created_at
        ),
    }


def serialize_incident_stakeholder(stakeholder):
    user = stakeholder.user if stakeholder.user_id else None

    return {
        "id": stakeholder.id,
        "incident_id": stakeholder.group_id,
        "user_id": stakeholder.user_id,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
        } if user else None,
        "email": stakeholder.email,
        "display_name": stakeholder.display_name,
        "role": stakeholder.role,
        "source": stakeholder.source,
        "notify_on_created": stakeholder.notify_on_created,
        "notify_on_priority_change": stakeholder.notify_on_priority_change,
        "notify_on_status_change": stakeholder.notify_on_status_change,
        "notify_on_resolved": stakeholder.notify_on_resolved,
        "notify_on_comment": bool(getattr(stakeholder, "notify_on_comment", True)),
        "active": stakeholder.active,
        "created_by_id": stakeholder.created_by_id,
        "created_at": stakeholder.created_at.isoformat() if stakeholder.created_at else None,
        "updated_at": stakeholder.updated_at.isoformat() if stakeholder.updated_at else None,
    }


def serialize_incident(group, *, current_user=None, include_details=False):
    data = serialize_alert_group(
        group,
        current_user=current_user,
        include_details=include_details,
        include_payload=include_details,
    )

    data["incident_id"] = group.id
    data["priority"] = {
        "id": group.priority_id,
        "slug": group.priority_slug,
        "order": group.priority_order,
        "set_manually": group.priority_set_manually,
        "set_by_id": group.priority_set_by_id,
        "set_at": group.priority_set_at.isoformat() if group.priority_set_at else None,
    }

    data["maintenance"] = {
        "window_id": group.maintenance_window_id,
        "behavior": group.maintenance_behavior,
        "suppressed": group.maintenance_suppressed,
    }

    data["active_maintenance"] = serialize_attached_maintenance_ref(group)

    return data


def serialize_maintenance_window_scope(scope):
    return {
        "id": scope.id,
        "maintenance_window_id": scope.maintenance_window_id,
        "scope_type": scope.scope_type,
        "group_id": scope.group_id,
        "team_id": scope.team_id,
        "service_id": scope.service_id,
        "route_id": scope.route_id,
        "created_at": scope.created_at.isoformat() if scope.created_at else None,
    }


def serialize_attached_maintenance_ref(obj):
    window = None
    window_id = getattr(obj, "maintenance_window_id", None)

    if window_id:
        try:
            window = obj.maintenance_window
        except Exception:
            window = None

    behavior = (
        getattr(obj, "maintenance_behavior", None)
        or getattr(window, "behavior", None)
    )

    suppressed = bool(getattr(obj, "maintenance_suppressed", False))

    if not window and not behavior and not suppressed:
        return None

    return {
        "id": getattr(window, "id", None),
        "name": getattr(window, "name", None) or "Maintenance",
        "status": (
            maintenance_repo.get_effective_window_status(window)
            if window
            else None
        ),
        "behavior": behavior,
        "timezone": getattr(window, "timezone", None),
        "starts_at": window.starts_at.isoformat() if window and window.starts_at else None,
        "ends_at": window.ends_at.isoformat() if window and window.ends_at else None,
        "occurrence": (
            serialize_maintenance_window_occurrence(window)
            if window
            else None
        ),
        "suppressed": suppressed,
    }


def serialize_maintenance_window(window, include_scopes=True):
    data = {
        "id": window.id,
        "group_id": window.group_id,
        "group_name": window.group.name if window.group_id else None,
        "team_id": window.team_id,
        "team_name": window.team.name if window.team_id else None,
        "name": window.name,
        "description": window.description,
        "status": maintenance_repo.get_effective_window_status(window),
        "stored_status": window.status,
        "behavior": window.behavior,
        "timezone": window.timezone,
        "rrule": window.rrule,
        "starts_at": serialize_local_datetime(window.starts_at),
        "ends_at": serialize_local_datetime(window.ends_at),
        "occurrence": serialize_maintenance_window_occurrence(window),
        "enabled": window.enabled,
        "deleted": window.deleted,
        "cancelled_by_id": window.cancelled_by_id,
        "cancelled_at": window.cancelled_at.isoformat() if window.cancelled_at else None,
        "cancel_reason": window.cancel_reason,
        "created_at": window.created_at.isoformat() if getattr(window, "created_at", None) else None,
        "updated_at": window.updated_at.isoformat() if getattr(window, "updated_at", None) else None,
    }

    if include_scopes:
        data["scopes"] = [
            serialize_maintenance_window_scope(scope)
            for scope in maintenance_repo.list_maintenance_window_scopes(window)
        ]

    return data


def _as_dict(value):
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}

        return parsed if isinstance(parsed, dict) else {}

    return {}


def _isoformat(value):
    return value.isoformat() if value else None


def _extract_alert_annotations(payload):
    annotations = payload.get("annotations")
    if isinstance(annotations, dict):
        return annotations

    common_annotations = payload.get("commonAnnotations")
    if isinstance(common_annotations, dict):
        return common_annotations

    nested_alert = payload.get("alert")
    if isinstance(nested_alert, dict):
        nested_annotations = nested_alert.get("annotations")
        if isinstance(nested_annotations, dict):
            return nested_annotations

    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        first_alert = alerts[0]
        if isinstance(first_alert, dict):
            nested_annotations = first_alert.get("annotations")
            if isinstance(nested_annotations, dict):
                return nested_annotations

    return {}


def _add_optional_incident_alert_fields(data, alert):
    optional_fields = (
        "priority_id",
        "priority_slug",
        "priority_order",
        "maintenance_window_id",
        "maintenance_behavior",
        "maintenance_suppressed",
    )

    for field_name in optional_fields:
        if hasattr(alert, field_name):
            data[field_name] = getattr(alert, field_name)

    if "priority_slug" in data and not data["priority_slug"]:
        data["priority_slug"] = "p3"

    if "priority_order" in data and not data["priority_order"]:
        data["priority_order"] = 3

    if "maintenance_suppressed" in data:
        data["maintenance_suppressed"] = bool(data["maintenance_suppressed"])


def serialize_incident_alert(alert):
    payload = _as_dict(getattr(alert, "payload", None))

    data = {
        "id": alert.id,
        "group_id": alert.group_id,
        "incident_id": alert.group_id,
        "team_id": alert.team_id,
        "route_id": alert.route_id,
        "rotation_id": alert.rotation_id,
        "escalation_policy_id": alert.escalation_policy_id,
        "escalation_rule_id": alert.escalation_rule_id,
        "service_id": alert.service_id,
        "assignee_id": alert.assignee_id,

        "source": alert.source,
        "external_id": alert.external_id,
        "dedup_key": alert.dedup_key,
        "group_key": alert.group_key,

        "title": alert.title,
        "message": alert.message,
        "severity": alert.severity,
        "status": alert.status,
        "previous_status": alert.previous_status,

        "labels": _as_dict(alert.labels),
        "annotations": _extract_alert_annotations(payload),
        "payload": payload,

        "silenced": alert.silenced,

        "acknowledged_by_id": alert.acknowledged_by_id,
        "acknowledged_at": _isoformat(alert.acknowledged_at),

        "next_escalation_at": _isoformat(alert.next_escalation_at),
        "last_escalated_at": _isoformat(alert.last_escalated_at),
        "escalation_repeat_count": alert.escalation_repeat_count,
        "escalation_level": alert.escalation_level,

        "last_notification_at": _isoformat(alert.last_notification_at),
        "reminder_count": alert.reminder_count,

        "first_seen_at": _isoformat(alert.first_seen_at),
        "last_seen_at": _isoformat(alert.last_seen_at),
        "resolved_at": _isoformat(alert.resolved_at),
    }

    _add_optional_incident_alert_fields(data, alert)

    return data


def serialize_maintenance_window_ref(window):
    if not window:
        return None

    return {
        "id": window.id,
        "name": window.name,
        "status": maintenance_repo.get_effective_window_status(window),
        "behavior": window.behavior,
        "timezone": window.timezone,
        "starts_at": serialize_local_datetime(window.starts_at),
        "ends_at": serialize_local_datetime(window.ends_at),
        "occurrence": serialize_maintenance_window_occurrence(window),
    }


def serialize_active_maintenance_for_scope(*, group_id=None, team_id=None, service_id=None, route_id=None):
    window = maintenance_repo.find_active_maintenance_window(
        group_id=group_id,
        team_id=team_id,
        service_id=service_id,
        route_id=route_id,
    )

    return serialize_maintenance_window_ref(window)


def serialize_maintenance_window_occurrence(window):
    occurrence = maintenance_repo.get_effective_window_occurrence(window)

    if not occurrence:
        return None

    starts_at = occurrence.get("starts_at")
    ends_at = occurrence.get("ends_at")

    return {
        "status": occurrence.get("status"),
        "starts_at": starts_at.isoformat() if starts_at else None,
        "ends_at": ends_at.isoformat() if ends_at else None,
        "timezone": occurrence.get("timezone"),
        "recurring": bool(occurrence.get("recurring")),
    }


def serialize_alert_explain_step(row):
    created_at = getattr(row, "created_at", None)

    return {
        "id": row.id,
        "position": row.position,
        "stage": row.stage,
        "code": row.code,
        "status": row.status,
        "title": row.title,
        "message": row.message,
        "data": row.data or {},
        "created_at": created_at.isoformat() if created_at else None,
    }


def serialize_alert_explain_trace(row, steps=None):
    started_at = getattr(row, "started_at", None)
    finished_at = getattr(row, "finished_at", None)

    return {
        "id": row.id,
        "trace_id": row.trace_id,
        "mode": row.mode,
        "group_id": row.group_id,
        "alert_id": row.alert_id,
        "source": row.source,
        "dedup_key": row.dedup_key,
        "status": row.status,
        "outcome": row.outcome,
        "reason": row.reason,
        "input_summary": row.input_summary or {},
        "result": row.result or {},
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "steps": [
            serialize_alert_explain_step(step)
            for step in (steps or [])
        ],
    }


def serialize_alert_processing_result(result, *, status=None, routing_error=None):
    group = result.group
    alert = result.alert

    payload = {
        "created": result.created_group,
        "id": getattr(group, "id", None),
        "group_id": getattr(group, "id", None),
        "alert_id": getattr(alert, "id", None),
        "status": (
            getattr(group, "status", None)
            or getattr(alert, "status", None)
            or status
        ),
        "outcome": result.outcome,
        "processing_status": result.processing_status,
        "reason": result.reason,
        "trace_id": result.trace_id,
        "routing_error": routing_error,
        "team_id": None,
        "team_slug": None,
        "route_id": None,
        "rotation_id": None,
        "assignee": None,
    }

    if group:
        payload["team_id"] = getattr(group, "team_id", None)
        payload["route_id"] = getattr(group, "route_id", None)
        payload["rotation_id"] = getattr(group, "rotation_id", None)

        team = getattr(group, "team", None)

        if team:
            payload["team_slug"] = getattr(team, "slug", None)

        assignee = getattr(group, "assignee", None)

        if assignee:
            payload["assignee"] = getattr(assignee, "username", None)

    if result.outcome == "routing_failed":
        payload["routing_error"] = result.reason or routing_error

    return payload
