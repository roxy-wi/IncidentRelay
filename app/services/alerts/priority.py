from datetime import datetime

from app.modules.db import incidents_repo, alerts_repo

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


def maybe_apply_auto_priority_to_group(group, priority):
    """
    Update incident priority automatically.

    Manual priority must never be overwritten by incoming alert severity.
    For auto priority, only upgrade to a more severe priority.
    Example: p3 -> p1 is allowed, p1 -> p3 is not automatic.
    """
    if not group or not priority:
        return group

    if getattr(group, "priority_set_manually", False):
        return group

    current_order = group.priority_order or 999

    if priority.level >= current_order:
        return group

    group.priority = priority.id
    group.priority_slug = priority.slug
    group.priority_order = priority.level
    group.priority_set_manually = False
    group.updated_at = datetime.utcnow()

    group.save(only=[
        group.__class__.priority,
        group.__class__.priority_slug,
        group.__class__.priority_order,
        group.__class__.priority_set_manually,
        group.__class__.updated_at,
    ])

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="priority_auto_updated",
        message=f"Priority automatically updated to {priority.slug}",
    )

    return group
