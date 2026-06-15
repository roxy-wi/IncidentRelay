from app.modules.db import alerts_repo


def maintenance_create_kwargs(maintenance_decision):
    if not maintenance_decision or not maintenance_decision.window:
        return {}

    return {
        "maintenance_window": maintenance_decision.window,
        "maintenance_behavior": maintenance_decision.behavior,
        "maintenance_suppressed": maintenance_decision.suppress_notifications,
    }


def apply_maintenance_to_existing_alert(alert, maintenance_decision):
    if not maintenance_decision or not maintenance_decision.window:
        return

    alert.maintenance_window = maintenance_decision.window
    alert.maintenance_behavior = maintenance_decision.behavior
    alert.maintenance_suppressed = maintenance_decision.suppress_notifications


def maybe_apply_maintenance_to_group(group, maintenance_decision):
    if not maintenance_decision or not maintenance_decision.window:
        return

    group.maintenance_window = maintenance_decision.window
    group.maintenance_behavior = maintenance_decision.behavior
    group.maintenance_suppressed = maintenance_decision.suppress_notifications
    group.save()


def record_maintenance_match(group, maintenance_decision, *, alert_id=None):
    """Write timeline event when an alert/incident matched maintenance."""
    if not group or not maintenance_decision or not maintenance_decision.matched:
        return

    window = maintenance_decision.window

    alerts_repo.create_alert_event(
        alert_id=alert_id,
        group_id=group.id,
        event_type="maintenance_matched",
        message=(
            f"Matched maintenance window: {window.name}"
            if window
            else "Matched maintenance window"
        ),
    )
