from app.modules.db import alerts_repo, incidents_repo
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.notifications.delivery import update_alert_messages


def set_incident_priority(*, group_id, priority, user_id=None):
    if not priority:
        raise ValueError("priority is required")

    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    old_priority = group.priority_slug

    group = incidents_repo.set_incident_priority(
        group.id,
        priority,
        user_id=user_id,
        manual=True,
    )

    if old_priority != group.priority_slug:
        update_alert_messages(group, event_type="priority_changed")
        notify_stakeholders(
            group,
            "priority_changed",
            old_value=old_priority,
        )

    return group


