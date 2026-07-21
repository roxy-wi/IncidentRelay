from datetime import datetime

from app.modules.db import incidents_repo, alerts_repo
from app.modules.common import utc_now

PRIORITY_DISPLAY_LABELS = {
    "p1": "P1 Critical",
    "p2": "P2 High",
    "p3": "P3 Medium",
    "p4": "P4 Low",
    "p5": "P5 Informational",
}


def alert_priority_slug(alert, default="p3"):
    """Return normalized incident priority slug for an alert group."""
    priority = getattr(alert, "priority", None)

    if priority and getattr(priority, "slug", None):
        return str(priority.slug).strip().lower()

    slug = getattr(alert, "priority_slug", None)

    if slug:
        return str(slug).strip().lower()

    return default


def alert_priority_short_label(alert):
    """Return compact priority label, for example P1."""
    return alert_priority_slug(alert).upper()


def alert_priority_label(alert):
    """Return human-readable priority label."""
    slug = alert_priority_slug(alert)
    short_label = slug.upper()

    priority = getattr(alert, "priority", None)
    priority_name = getattr(priority, "name", None)

    if priority_name:
        priority_name = str(priority_name).strip()

        if priority_name.upper().startswith(f"{short_label} "):
            return priority_name

        if priority_name.upper() == short_label:
            return priority_name

        return f"{short_label} {priority_name}"

    return PRIORITY_DISPLAY_LABELS.get(slug, short_label)


def format_alert_title_with_priority(alert):
    """Return alert title prefixed with priority, for example [P1] DiskFull."""
    title = getattr(alert, "title", None) or "Alert"

    return f"[{alert_priority_short_label(alert)}] {title}"


def incident_priority_from_alert(alert_data):
    """Resolve incident priority from alert severity."""
    return incidents_repo.priority_from_severity(
        alert_data.get("severity")
    )


def incident_priority_create_kwargs(priority):
    """Return kwargs for AlertGroup/Alert priority fields."""
    return {
        "priority": priority.id if priority else None,
        "priority_slug": priority.slug if priority else "p3",
        "priority_order": priority.level if priority else 3,
    }


def apply_priority_to_existing_alert(alert, priority):
    """Attach resolved priority to an existing child alert."""
    if not priority:
        alert.priority = None
        alert.priority_slug = "p3"
        alert.priority_order = 3
        return alert

    alert.priority = priority.id
    alert.priority_slug = priority.slug
    alert.priority_order = priority.level

    return alert



def group_priority_state(group):
    """Return the persisted priority fields that belong to an incident."""
    if not group:
        return None

    return {
        "priority_id": getattr(group, "priority_id", None),
        "priority_slug": getattr(group, "priority_slug", None),
        "priority_order": getattr(group, "priority_order", None),
        "priority_set_manually": bool(
            getattr(group, "priority_set_manually", False)
        ),
    }


def restore_group_priority_state(group, state):
    """Restore priority fields changed by a generic group recalculation."""
    if not group or not state:
        return group

    current_state = group_priority_state(group)

    if current_state == state:
        return group

    group.priority = state["priority_id"]
    group.priority_slug = state["priority_slug"]
    group.priority_order = state["priority_order"]
    group.priority_set_manually = state["priority_set_manually"]

    group.save(only=[
        group.__class__.priority,
        group.__class__.priority_slug,
        group.__class__.priority_order,
        group.__class__.priority_set_manually,
    ])

    return group


def _save_auto_priority(group, priority, *, event_type, message):
    """Persist an automatically resolved incident priority."""
    current_priority_id = getattr(group, "priority_id", None)

    if (
        current_priority_id == priority.id
        and group.priority_slug == priority.slug
        and group.priority_order == priority.level
    ):
        return group

    group.priority = priority.id
    group.priority_slug = priority.slug
    group.priority_order = priority.level
    group.priority_set_manually = False
    group.updated_at = utc_now()

    group.save(only=[
        group.__class__.priority,
        group.__class__.priority_slug,
        group.__class__.priority_order,
        group.__class__.priority_set_manually,
        group.__class__.updated_at,
    ])

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type=event_type,
        message=message,
    )

    return group


def maybe_apply_auto_priority_to_group(group, priority):
    """
    Raise incident priority automatically.

    Manual priority must never be overwritten. Lower numeric levels are more
    severe, so p3 -> p1 is allowed while p1 -> p3 is ignored.
    """
    if not group or not priority:
        return group

    if getattr(group, "priority_set_manually", False):
        return group

    current_order = group.priority_order or 999

    if priority.level >= current_order:
        return group

    return _save_auto_priority(
        group,
        priority,
        event_type="priority_auto_updated",
        message=(
            "Priority automatically raised from "
            f"{group.priority_slug or 'unknown'} to {priority.slug}"
        ),
    )


def _is_priority_model(value):
    return bool(
        value
        and getattr(value, "id", None) is not None
        and getattr(value, "slug", None)
        and getattr(value, "level", None) is not None
    )


def recalculate_auto_priority_from_active_alerts(
    group,
    *,
    fallback_priority=None,
):
    """Set incident priority from active alerts or the policy fallback."""
    if not group or getattr(group, "priority_set_manually", False):
        return group

    active_alerts = [
        alert
        for alert in alerts_repo.list_alerts_for_group(group.id)
        if alert.status != "resolved" and getattr(alert, "priority_id", None)
    ]

    if active_alerts:
        priority_alert = min(
            active_alerts,
            key=lambda alert: alert.priority_order or 999,
        )
        priority = priority_alert.priority
    else:
        priority = fallback_priority

    if not _is_priority_model(priority):
        return group

    return _save_auto_priority(
        group,
        priority,
        event_type="priority_auto_recalculated",
        message=(
            "Priority automatically recalculated from "
            f"{group.priority_slug or 'unknown'} to {priority.slug}"
        ),
    )


def apply_priority_resolution_to_group(group, resolution):
    """Apply a priority policy resolution to an existing incident."""
    if not group or not resolution:
        return group

    if getattr(group, "priority_set_manually", False):
        return group

    if resolution.update_mode == "initial_only":
        return group

    if resolution.update_mode == "recalculate":
        return recalculate_auto_priority_from_active_alerts(group)

    if not resolution.priority:
        return group

    return maybe_apply_auto_priority_to_group(
        group,
        resolution.priority,
    )
