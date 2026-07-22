import json

from app.services.serializers.alerts import serialize_alert_group, serialize_attached_maintenance_ref


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
        "orchestration_suppressed",
        "orchestration_suppress_reason",
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

    if "orchestration_suppressed" in data:
        data["orchestration_suppressed"] = bool(
            data["orchestration_suppressed"]
        )


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
