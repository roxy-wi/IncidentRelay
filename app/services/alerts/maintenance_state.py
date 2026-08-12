from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.common import utc_now
from app.modules.db import alerts_repo, audit_repo, maintenance_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    MaintenanceWindow,
    MaintenanceWindowAlertApplication,
)
from app.services import escalation_policies as escalation_policy_service

SUPPRESS_NOTIFICATIONS_BEHAVIOR = "suppress_notifications"
PAUSE_ESCALATION_BEHAVIOR = "pause_escalation_only"
MAINTENANCE_INCIDENT_BEHAVIOR = "create_maintenance_incident"
SUPPRESS_INCIDENT_BEHAVIOR = "suppress_incident"


def maintenance_create_kwargs(maintenance_decision) -> dict[str, object]:
    if not maintenance_decision or not maintenance_decision.window:
        return {}

    return {
        "maintenance_window": maintenance_decision.window,
        "maintenance_behavior": maintenance_decision.behavior,
        "maintenance_suppressed": maintenance_decision.suppress_notifications,
    }


def _occurrence_start_utc(window: MaintenanceWindow, now=None) -> datetime | None:
    occurrence = maintenance_repo.get_effective_window_occurrence(window, now=now)
    if not occurrence:
        return None
    starts_at = occurrence.get("starts_at")
    if not starts_at:
        return None
    try:
        zone = ZoneInfo(window.timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return (
        starts_at.replace(tzinfo=zone)
        .astimezone(dt_timezone.utc)
        .replace(tzinfo=None)
    )


def should_apply_window_to_group(
    window: MaintenanceWindow,
    group: AlertGroup,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether an active window may affect this existing group."""
    if not window or not group or group.status == "resolved":
        return False
    if window.behavior == SUPPRESS_INCIDENT_BEHAVIOR:
        return False
    if not maintenance_repo.is_window_active_now(window, now=now):
        return False
    if window.apply_to_existing:
        return True
    occurrence_start = _occurrence_start_utc(window, now=now)
    if not occurrence_start:
        return False
    first_seen_at = group.first_seen_at or group.created_at
    return bool(first_seen_at and first_seen_at >= occurrence_start)


def _group_matches_window_scope(
    window: MaintenanceWindow,
    group: AlertGroup,
) -> bool:
    """Return whether the group still belongs to at least one window scope."""
    for scope in maintenance_repo.list_maintenance_window_scopes(window.id):
        if scope.scope_type == "group":
            if group.team_id and group.team.group_id == scope.group_id:
                return True
        elif scope.scope_type == "team" and group.team_id == scope.team_id:
            return True
        elif scope.scope_type == "service" and group.service_id == scope.service_id:
            return True
        elif scope.scope_type == "route" and group.route_id == scope.route_id:
            return True
    return False


def _iter_batches(items, batch_size: int | None):
    """Yield deterministic in-memory batches without dropping later rows."""
    size = max(int(batch_size or len(items) or 1), 1)
    for offset in range(0, len(items), size):
        yield items[offset:offset + size]


def apply_maintenance_to_existing_alert(alert: Alert, maintenance_decision) -> None:
    if not maintenance_decision or not maintenance_decision.window:
        return
    if alert.group and not should_apply_window_to_group(
        maintenance_decision.window,
        alert.group,
    ):
        return
    alert.maintenance_window = maintenance_decision.window
    alert.maintenance_behavior = maintenance_decision.behavior
    alert.maintenance_suppressed = maintenance_decision.suppress_notifications


def _active_group_applications(
    group: AlertGroup,
) -> list[MaintenanceWindowAlertApplication]:
    return maintenance_repo.list_group_applications(group, active_only=True)


def _application_effect_is_active(
    application: MaintenanceWindowAlertApplication,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether an active application still affects its alert group.

    Application rows remain active until the lifecycle reconciler records their
    release. Runtime notification and escalation checks must still notice that
    a window has already ended, otherwise an expired window can suppress the
    group until the scheduler performs its next reconciliation pass.
    """
    if not application or not application.active:
        return False

    window = application.maintenance_window
    if not window or getattr(window, "deleted", False):
        return False

    if application.retained_at is not None:
        return True

    if maintenance_repo.is_window_active_now(window, now=now):
        return True

    # When automatic reactivation is disabled, the effect intentionally
    # remains in force after expiry, disable, or cancellation. The scheduler
    # later marks the row as retained, but runtime checks must preserve the
    # configured behavior even before that reconciliation occurs.
    return not bool(window.reactivate_on_end)


def _effective_group_applications(
    group: AlertGroup,
    *,
    now: datetime | None = None,
) -> list[MaintenanceWindowAlertApplication]:
    return [
        application
        for application in _active_group_applications(group)
        if _application_effect_is_active(application, now=now)
    ]


def is_notification_lifecycle_suppressed(
    group: AlertGroup,
    *,
    now: datetime | None = None,
) -> bool:
    if not group:
        return False
    if any(
        application.behavior == SUPPRESS_NOTIFICATIONS_BEHAVIOR
        for application in _effective_group_applications(group, now=now)
    ):
        return True
    window = getattr(group, "maintenance_window", None)
    behavior = getattr(window, "behavior", None) or group.maintenance_behavior
    return (
        behavior == SUPPRESS_NOTIFICATIONS_BEHAVIOR
        and maintenance_repo.is_window_active_now(window, now=now)
    )


def is_escalation_lifecycle_paused(
    group: AlertGroup,
    *,
    now: datetime | None = None,
) -> bool:
    if not group:
        return False
    paused_behaviors = {
        SUPPRESS_NOTIFICATIONS_BEHAVIOR,
        PAUSE_ESCALATION_BEHAVIOR,
        MAINTENANCE_INCIDENT_BEHAVIOR,
    }
    if any(
        application.behavior in paused_behaviors
        for application in _effective_group_applications(group, now=now)
    ):
        return True
    window = getattr(group, "maintenance_window", None)
    return bool(
        group.maintenance_behavior in paused_behaviors
        and maintenance_repo.is_window_active_now(window, now=now)
    )


def pause_notification_lifecycle(group: AlertGroup) -> bool:
    changed = False
    newly_suppressed = not bool(group.maintenance_suppressed)
    if newly_suppressed:
        group.maintenance_suppressed = True
        changed = True
    if group.notification_pending or group.notification_due_at or group.notification_reason:
        group.notification_pending = False
        group.notification_due_at = None
        group.notification_reason = None
        changed = True
    if group.next_escalation_at is not None:
        group.next_escalation_at = None
        changed = True
    if changed:
        group.updated_at = utc_now()
        group.save()
    if newly_suppressed:
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="maintenance_notifications_paused",
            message="Notification, reminder, and escalation processing paused by maintenance",
        )
    return changed


def resume_notification_lifecycle(
    group: AlertGroup,
    *,
    now: datetime | None = None,
) -> bool:
    if not group or not bool(group.maintenance_suppressed):
        return False
    if is_notification_lifecycle_suppressed(group, now=now):
        return False
    now = now or utc_now()
    next_escalation_at = None
    if (
        group.status == "firing"
        and group.escalation_policy_id
        and group.escalation_rule_id
        and not is_escalation_lifecycle_paused(group, now=now)
    ):
        next_escalation_at = escalation_policy_service.get_next_escalation_at(
            group.escalation_rule,
            now,
        )
    updated = (
        AlertGroup.update(
            maintenance_suppressed=False,
            reminder_count=0,
            next_escalation_at=next_escalation_at,
            updated_at=now,
        )
        .where(
            AlertGroup.id == group.id,
            AlertGroup.maintenance_suppressed == True,  # noqa: E712
        )
        .execute()
    )
    if not updated:
        return False
    group.maintenance_suppressed = False
    group.reminder_count = 0
    group.next_escalation_at = next_escalation_at
    group.updated_at = now
    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="maintenance_notifications_resumed",
        message="Maintenance ended; notification and escalation processing resumed",
    )
    return True


def _original_status_for_group(group: AlertGroup, fallback: str | None = None) -> str:
    if fallback and fallback not in {"maintenance", "resolved"}:
        return fallback
    for application in maintenance_repo.list_group_applications(group):
        if application.previous_status not in (None, "maintenance", "resolved"):
            return application.previous_status
    if group.previous_status not in (None, "maintenance", "resolved"):
        return group.previous_status
    return "firing"


def _write_application_audit(
    action: str,
    application: MaintenanceWindowAlertApplication,
    *,
    trigger_source: str,
    actor_user_id: int | None,
    previous_state: str | None,
    new_state: str | None,
) -> None:
    group = application.alert_group
    window = application.maintenance_window
    audit_repo.create_audit_log(
        action=action,
        object_type="alert_group",
        object_id=group.id,
        group_id=group.team.group_id if group.team_id and group.team else None,
        team_id=group.team_id,
        user_id=actor_user_id,
        message=None,
        data={
            "maintenance_window_id": window.id,
            "maintenance_window_name": window.name,
            "behavior": application.behavior,
            "previous_state": previous_state,
            "new_state": new_state,
            "trigger_source": trigger_source,
        },
    )


def _set_representative_maintenance(group: AlertGroup, applications) -> None:
    representative = applications[0] if applications else None
    group.maintenance_window = (
        representative.maintenance_window_id if representative else None
    )
    group.maintenance_behavior = representative.behavior if representative else None
    Alert.update(
        maintenance_window=group.maintenance_window_id,
        maintenance_behavior=group.maintenance_behavior,
        maintenance_suppressed=group.maintenance_suppressed,
    ).where(
        Alert.group == group.id,
        Alert.status != "resolved",
    ).execute()


def _recompute_group_effects(
    group: AlertGroup,
    *,
    now: datetime,
    fallback_status: str | None = None,
    notify_on_resume: bool = False,
) -> None:
    applications = _active_group_applications(group)
    behaviors = {application.behavior for application in applications}
    create_maintenance = MAINTENANCE_INCIDENT_BEHAVIOR in behaviors
    suppress_notifications = SUPPRESS_NOTIFICATIONS_BEHAVIOR in behaviors
    pause_escalation = bool(
        behaviors
        & {
            SUPPRESS_NOTIFICATIONS_BEHAVIOR,
            PAUSE_ESCALATION_BEHAVIOR,
            MAINTENANCE_INCIDENT_BEHAVIOR,
        }
    )
    was_maintenance = group.status == "maintenance"
    was_suppressed = bool(group.maintenance_suppressed)

    if create_maintenance and group.status != "resolved":
        original_status = _original_status_for_group(group, fallback_status)
        if group.status != "maintenance":
            group.previous_status = group.status
        group.status = "maintenance"
        group.resolved_at = None
        Alert.update(
            status="maintenance",
            previous_status=Alert.status,
            maintenance_suppressed=False,
        ).where(
            Alert.group == group.id,
            Alert.status.not_in(("resolved", "maintenance")),
        ).execute()
        if not any(app.previous_status for app in applications):
            applications[0].previous_status = original_status
            applications[0].save(only=[applications[0].__class__.previous_status])
    elif was_maintenance:
        restore_status = _original_status_for_group(group, fallback_status)
        Alert.update(
            status=Alert.previous_status,
            previous_status=None,
        ).where(
            Alert.group == group.id,
            Alert.status == "maintenance",
            Alert.previous_status.is_null(False),
        ).execute()
        Alert.update(status="firing").where(
            Alert.group == group.id,
            Alert.status == "maintenance",
        ).execute()
        group.status = restore_status
        group.resolved_at = None
        group.resolved_by = None
        group.save()
        group = alerts_repo.recalculate_alert_group(group)
        if restore_status == "acknowledged" and group.status != "resolved":
            group.status = "acknowledged"

    if suppress_notifications:
        pause_notification_lifecycle(group)
    elif was_suppressed:
        resume_notification_lifecycle(group, now=now)

    if pause_escalation:
        group.next_escalation_at = None
        Alert.update(next_escalation_at=None).where(
            Alert.group == group.id,
            Alert.status != "resolved",
        ).execute()
    elif (
        group.status == "firing"
        and group.escalation_policy_id
        and group.escalation_rule_id
    ):
        group.next_escalation_at = escalation_policy_service.get_next_escalation_at(
            group.escalation_rule,
            now,
        )

    if create_maintenance:
        group.notification_pending = False
        group.notification_due_at = None
        group.notification_reason = None
        group.next_escalation_at = None

    group.updated_at = now
    group.save()
    _set_representative_maintenance(group, applications)
    group.save()

    if (
        notify_on_resume
        and group.status == "firing"
        and not suppress_notifications
        and not create_maintenance
    ):
        from app.services.alerts.notification_queue import schedule_group_notification
        schedule_group_notification(group, reason="maintenance_ended", now=now)


def _apply_window_to_group(
    window: MaintenanceWindow,
    group: AlertGroup,
    *,
    now: datetime,
    occurrence_start: datetime | None,
    trigger_source: str,
    actor_user_id: int | None,
) -> bool:
    application = maintenance_repo.get_window_group_application(window, group)
    source = "existing"
    if occurrence_start and (group.first_seen_at or group.created_at) >= occurrence_start:
        source = "new"
    created_or_reactivated = application is None or not application.active
    previous_behavior = application.behavior if application else None
    behavior_changed = bool(application and previous_behavior != window.behavior)
    previous_state = group.status

    if application is None:
        previous_status = group.status
        if previous_status == "maintenance":
            previous_status = _original_status_for_group(group)
        application = MaintenanceWindowAlertApplication.create(
            maintenance_window=window,
            alert_group=group,
            behavior=window.behavior,
            application_source=source,
            previous_status=previous_status,
            occurrence_started_at=occurrence_start,
            active=True,
            applied_at=now,
        )
    else:
        if window.behavior == MAINTENANCE_INCIDENT_BEHAVIOR and not application.previous_status:
            application.previous_status = _original_status_for_group(group)
        application.behavior = window.behavior
        application.application_source = source
        application.occurrence_started_at = occurrence_start
        application.active = True
        application.applied_at = now if created_or_reactivated else application.applied_at
        application.retained_at = None
        application.released_at = None
        application.release_reason = None
        application.save()

    notify_on_resume = bool(
        behavior_changed
        and previous_behavior in {
            SUPPRESS_NOTIFICATIONS_BEHAVIOR,
            MAINTENANCE_INCIDENT_BEHAVIOR,
        }
        and window.behavior not in {
            SUPPRESS_NOTIFICATIONS_BEHAVIOR,
            MAINTENANCE_INCIDENT_BEHAVIOR,
        }
    )
    _recompute_group_effects(
        group,
        now=now,
        fallback_status=application.previous_status,
        notify_on_resume=notify_on_resume,
    )

    if created_or_reactivated or behavior_changed:
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="maintenance_applied",
            message=f"Maintenance applied: {window.name} ({window.behavior})",
        )
        _write_application_audit(
            "maintenance_window.alert_group_applied",
            application,
            trigger_source=trigger_source,
            actor_user_id=actor_user_id,
            previous_state=previous_state,
            new_state=AlertGroup.get_by_id(group.id).status,
        )
        return True
    return False


def _release_application(
    application: MaintenanceWindowAlertApplication,
    *,
    now: datetime,
    reason: str,
    trigger_source: str,
    actor_user_id: int | None,
) -> bool:
    if not application.active:
        return False
    group = application.alert_group
    previous_state = group.status
    fallback_status = application.previous_status
    application.active = False
    application.retained_at = None
    application.released_at = now
    application.release_reason = reason
    application.save()
    if application.behavior == PAUSE_ESCALATION_BEHAVIOR:
        group.reminder_count = 0
        group.save(only=[group.__class__.reminder_count])
    _recompute_group_effects(
        group,
        now=now,
        fallback_status=fallback_status,
        notify_on_resume=application.behavior in {
            SUPPRESS_NOTIFICATIONS_BEHAVIOR,
            MAINTENANCE_INCIDENT_BEHAVIOR,
        },
    )
    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="maintenance_released",
        message=f"Maintenance effect released: {application.maintenance_window.name}",
    )
    _write_application_audit(
        "maintenance_window.alert_group_released",
        application,
        trigger_source=trigger_source,
        actor_user_id=actor_user_id,
        previous_state=previous_state,
        new_state=AlertGroup.get_by_id(group.id).status,
    )
    return True


def _retain_application(
    application: MaintenanceWindowAlertApplication,
    *,
    now: datetime,
    trigger_source: str,
    actor_user_id: int | None,
) -> bool:
    if application.retained_at is not None:
        return False
    application.retained_at = now
    application.save(only=[application.__class__.retained_at])
    alerts_repo.create_alert_event(
        group_id=application.alert_group_id,
        event_type="maintenance_effect_retained",
        message=(
            "Maintenance ended, but its effect remains active because automatic "
            f"reactivation is disabled: {application.maintenance_window.name}"
        ),
    )
    _write_application_audit(
        "maintenance_window.alert_group_retained",
        application,
        trigger_source=trigger_source,
        actor_user_id=actor_user_id,
        previous_state=application.alert_group.status,
        new_state=application.alert_group.status,
    )
    return True


def reconcile_maintenance_window(
    window: MaintenanceWindow,
    *,
    now: datetime | None = None,
    trigger_source: str = "scheduler",
    actor_user_id: int | None = None,
    limit: int | None = None,
    force_release: bool = False,
) -> dict[str, int]:
    """Apply or release one window against unresolved groups idempotently."""
    now = now or utc_now()
    active = maintenance_repo.is_window_active_now(window, now=now)
    occurrence_start = _occurrence_start_utc(window, now=now) if active else None
    applied = released = retained = 0

    if active and window.behavior != SUPPRESS_INCIDENT_BEHAVIOR:
        candidates = maintenance_repo.list_unresolved_alert_groups_for_window(window)
        for batch in _iter_batches(candidates, limit):
            for group in batch:
                if not should_apply_window_to_group(window, group, now=now):
                    continue
                if _apply_window_to_group(
                    window,
                    group,
                    now=now,
                    occurrence_start=occurrence_start,
                    trigger_source=trigger_source,
                    actor_user_id=actor_user_id,
                ):
                    applied += 1

    applications = maintenance_repo.list_window_applications(window, active_only=True)
    for batch in _iter_batches(applications, limit):
        for application in batch:
            group = application.alert_group
            still_applicable = bool(
                active
                and window.behavior != SUPPRESS_INCIDENT_BEHAVIOR
                and group.status != "resolved"
                and _group_matches_window_scope(window, group)
                and should_apply_window_to_group(window, group, now=now)
            )
            if still_applicable:
                continue

            configuration_removed_effect = bool(
                active
                and (
                    window.behavior == SUPPRESS_INCIDENT_BEHAVIOR
                    or not _group_matches_window_scope(window, group)
                    or not should_apply_window_to_group(window, group, now=now)
                )
            )
            release_now = bool(
                force_release
                or group.status == "resolved"
                or configuration_removed_effect
                or window.reactivate_on_end
            )

            if release_now:
                if _release_application(
                    application,
                    now=now,
                    reason=(
                        "deleted"
                        if force_release
                        else "resolved"
                        if group.status == "resolved"
                        else "configuration_changed"
                        if configuration_removed_effect
                        else "window_inactive"
                    ),
                    trigger_source=trigger_source,
                    actor_user_id=actor_user_id,
                ):
                    released += 1
            elif _retain_application(
                application,
                now=now,
                trigger_source=trigger_source,
                actor_user_id=actor_user_id,
            ):
                retained += 1

    window.reconciled_at = now
    window.save(only=[window.__class__.reconciled_at])
    return {"applied": applied, "released": released, "retained": retained}


def reconcile_alert_group_maintenance(
    group: AlertGroup,
    *,
    now: datetime | None = None,
    trigger_source: str = "intake",
) -> dict[str, int]:
    """Apply every currently active matching window to one alert group."""
    now = now or utc_now()
    windows = maintenance_repo.list_active_maintenance_windows(
        group_id=group.team.group_id if group.team_id and group.team else None,
        team_id=group.team_id,
        service_id=group.service_id,
        route_id=group.route_id,
        now=now,
    )
    applied = 0
    matched_ids = set()
    for window in windows:
        if not should_apply_window_to_group(window, group, now=now):
            continue
        matched_ids.add(window.id)
        if _apply_window_to_group(
            window,
            group,
            now=now,
            occurrence_start=_occurrence_start_utc(window, now=now),
            trigger_source=trigger_source,
            actor_user_id=None,
        ):
            applied += 1
    return {"applied": applied, "matched": len(matched_ids)}


def process_maintenance_lifecycle(
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Reconcile all windows for scheduled start/end and configuration changes."""
    now = now or utc_now()
    result = {"windows": 0, "applied": 0, "released": 0, "retained": 0}
    windows = maintenance_repo.list_maintenance_windows(
        include_deleted=True,
        include_finished=True,
    )
    for window in windows:
        item = reconcile_maintenance_window(
            window,
            now=now,
            trigger_source="scheduler",
            limit=limit,
        )
        result["windows"] += 1
        for key in ("applied", "released", "retained"):
            result[key] += item[key]
    return result


def maybe_apply_maintenance_to_group(group: AlertGroup, maintenance_decision) -> None:
    if not group:
        return
    reconcile_alert_group_maintenance(group, trigger_source="intake")


def record_maintenance_match(
    group: AlertGroup,
    maintenance_decision,
    *,
    alert_id: int | None = None,
) -> None:
    if not group or not maintenance_decision or not maintenance_decision.matched:
        return
    window = maintenance_decision.window
    alerts_repo.create_alert_event(
        alert_id=alert_id,
        group_id=group.id,
        event_type="maintenance_matched",
        message=f"Matched maintenance window: {window.name}",
    )
