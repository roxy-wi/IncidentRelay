from app.modules.db import incidents_repo, maintenance_repo, business_services_repo
from app.services.incidents.responder_display import responder_target_label
from app.services.serializers.business_services import serialize_business_service_incident_impact, \
    serialize_alert_group_business_impact_summary
from app.services.serializers.channels import serialize_channel_short
from app.services.serializers.common import serialize_utc_datetime, attach_team_permissions
from app.services.serializers.rotations import serialize_rotation_short, serialize_escalation_policy_short
from app.services.serializers.services import serialize_service_short, serialize_maintenance_window_occurrence
from app.services.serializers.teams import serialize_team_short
from app.services.serializers.users import serialize_user_short


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


def serialize_alert_event(event):
    """
    Serialize an alert event.
    """

    return {
        "id": event.id,
        "event_type": event.event_type,
        "message": event.message,
        "user": serialize_user_short(event.user),
        "created_at": serialize_utc_datetime(event.created_at),
    }


def serialize_correlation_alert_group_ref(group):
    """Serialize compact alert group reference for correlation UI."""
    if not group:
        return None

    service = group.service if getattr(group, "service_id", None) else None

    return {
        "id": group.id,
        "title": group.title,
        "status": group.status,
        "severity": group.severity,
        "priority": getattr(group, "priority_slug", None),
        "service_id": getattr(service, "id", None),
        "service_slug": getattr(service, "slug", None),
        "service_name": getattr(service, "name", None),
        "source": group.source,
        "last_seen_at": serialize_utc_datetime(group.last_seen_at),
    }


def serialize_alert_group_correlation(correlation, current_group_id=None):
    """Serialize one saved alert group correlation."""
    root_group = correlation.root_group
    related_group = correlation.related_group

    if current_group_id and related_group.id == current_group_id:
        role = "possible_symptom"
        peer_group = root_group
    elif current_group_id and root_group.id == current_group_id:
        role = "possible_root_cause"
        peer_group = related_group
    else:
        role = "related"
        peer_group = related_group

    return {
        "id": correlation.id,
        "role": role,
        "relation_type": correlation.relation_type,
        "direction": correlation.direction,
        "score": correlation.score,
        "depth": correlation.depth,
        "dependency_type": correlation.dependency_type,
        "criticality": correlation.criticality,
        "reason": correlation.reason,
        "active": correlation.active,
        "first_seen_at": serialize_utc_datetime(correlation.first_seen_at),
        "last_seen_at": serialize_utc_datetime(correlation.last_seen_at),
        "root_group": serialize_correlation_alert_group_ref(root_group),
        "related_group": serialize_correlation_alert_group_ref(related_group),
        "peer_group": serialize_correlation_alert_group_ref(peer_group),
    }


def serialize_alert_group_correlations(group):
    """Serialize active saved correlations for alert group details."""
    from app.services.alerts.correlation import (
        get_saved_alert_group_correlation_summary,
    )

    summary = get_saved_alert_group_correlation_summary(group)

    root_candidates = [
        serialize_alert_group_correlation(item, current_group_id=group.id)
        for item in summary["root_candidates"]
    ]

    downstream_impacts = [
        serialize_alert_group_correlation(item, current_group_id=group.id)
        for item in summary["downstream_impacts"]
    ]

    return {
        "root_candidates": root_candidates,
        "downstream_impacts": downstream_impacts,
        "total": len(root_candidates) + len(downstream_impacts),
    }


def serialize_alert_group_correlation_summary(group):
    """Serialize compact saved correlation summary for alert list rows."""
    from app.services.alerts.correlation import (
        get_saved_alert_group_correlation_summary,
    )

    summary = get_saved_alert_group_correlation_summary(group)

    root_candidates = summary["root_candidates"]
    downstream_impacts = summary["downstream_impacts"]

    root_count = len(root_candidates)
    downstream_count = len(downstream_impacts)
    total = root_count + downstream_count

    best_score = 0

    if root_candidates:
        best_score = max(best_score, max(item.score for item in root_candidates))

    if downstream_impacts:
        best_score = max(
            best_score,
            max(item.score for item in downstream_impacts),
        )

    roles = []

    if root_count:
        roles.append("possible_symptom")

    if downstream_count:
        roles.append("possible_root_cause")

    return {
        "total": total,
        "root_candidates": root_count,
        "downstream_impacts": downstream_count,
        "best_score": best_score,
        "roles": roles,
        "has_correlation": total > 0,
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
        "created_at": serialize_utc_datetime(notification.created_at),
        "updated_at": serialize_utc_datetime(notification.updated_at),
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
        "orchestration_suppressed": bool(
            getattr(group, "orchestration_suppressed", False)
        ),
        "orchestration_suppress_reason": getattr(
            group, "orchestration_suppress_reason", None
        ),
        "correlation_summary": serialize_alert_group_correlation_summary(group),
        "business_impact_summary": serialize_alert_group_business_impact_summary(group),
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
        data["correlations"] = serialize_alert_group_correlations(group)
        data["business_impacts"] = [
            serialize_business_service_incident_impact(impact)
            for impact in business_services_repo.list_active_incident_impacts(group.id)
        ]

    data["active_maintenance"] = serialize_attached_maintenance_ref(group)

    return attach_team_permissions(data, team.id if team else None, current_user)


def serialize_alert_comment(comment):
    user = comment.user if getattr(comment, "user_id", None) else None

    created_at = serialize_utc_datetime(comment.created_at)
    updated_at = serialize_utc_datetime(comment.updated_at)

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


def serialize_alert_explain_step(row):
    created_at = serialize_utc_datetime(getattr(row, "created_at", None))

    return {
        "id": row.id,
        "position": row.position,
        "stage": row.stage,
        "code": row.code,
        "status": row.status,
        "title": row.title,
        "message": row.message,
        "data": row.data or {},
        "created_at": created_at,
    }


def serialize_alert_explain_trace(row, steps=None):
    started_at = serialize_utc_datetime(getattr(row, "started_at", None))
    finished_at = serialize_utc_datetime(getattr(row, "finished_at", None))

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
        "started_at": started_at,
        "finished_at": finished_at,
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
