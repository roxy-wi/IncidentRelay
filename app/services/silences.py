from __future__ import annotations

from datetime import datetime

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db import alerts_repo, audit_repo, silences_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    Silence,
    SilenceAlertApplication,
)
from app.services.alerts.escalation import apply_initial_escalation_policy_assignment
from app.services.alerts.notification_queue import schedule_group_notification
from app.services.routing.matcher.match_context import alert_rule_matches


RELEASE_REASON_DISABLED = "disabled"
RELEASE_REASON_EXPIRED = "expired"
RELEASE_REASON_UPDATED = "updated"


def find_active_silences(
    team_id: int | None,
    alert_data: dict | Alert,
    *,
    now: datetime | None = None,
) -> list[Silence]:
    """Return all active silences matching an alert."""
    if not team_id:
        return []

    return [
        silence
        for silence in silences_repo.list_active_silences(team_id, now=now)
        if alert_rule_matches(
            alert_data,
            silence,
            team=silence.team,
        )
    ]


def find_active_silence(
    team_id: int | None,
    alert_data: dict | Alert,
    *,
    now: datetime | None = None,
) -> Silence | None:
    """Return the first active silence matching an alert."""
    silences = find_active_silences(team_id, alert_data, now=now)
    return silences[0] if silences else None


def _silence_is_active(
    silence: Silence,
    now: datetime,
) -> bool:
    return bool(
        silence.enabled
        and not silence.deleted
        and silence.starts_at <= now < silence.ends_at
    )


def _alert_matches_silence(alert: Alert, silence: Silence) -> bool:
    return alert_rule_matches(
        alert,
        silence,
        team=alert.team,
        route=alert.route,
        service=alert.service,
        priority=alert.priority_slug,
    )


def _record_transition_audit(
    *,
    action: str,
    group: AlertGroup,
    silence: Silence | None,
    previous_status: str,
    new_status: str,
    trigger_source: str,
) -> None:
    audit_repo.create_audit_log(
        action=action,
        object_type="alert_group",
        object_id=group.id,
        group_id=group.team.group_id if group.team else None,
        team_id=group.team_id,
        message=(
            f"Silence {silence.name} changed alert group "
            f"from {previous_status} to {new_status}"
            if silence
            else (
                f"Silence lifecycle changed alert group from "
                f"{previous_status} to {new_status}"
            )
        ),
        data={
            "silence_id": silence.id if silence else None,
            "silence_name": silence.name if silence else None,
            "previous_status": previous_status,
            "new_status": new_status,
            "trigger_source": trigger_source,
        },
    )


def _record_alert_application_audit(
    *,
    action: str,
    alert: Alert,
    silence: Silence | None,
    previous_status: str,
    new_status: str,
    trigger_source: str,
) -> None:
    audit_repo.create_audit_log(
        action=action,
        object_type="alert",
        object_id=alert.id,
        group_id=alert.team.group_id if alert.team else None,
        team_id=alert.team_id,
        message=(
            f"Silence {silence.name} changed alert "
            f"from {previous_status} to {new_status}"
            if silence
            else (
                f"Silence lifecycle changed alert from "
                f"{previous_status} to {new_status}"
            )
        ),
        data={
            "silence_id": silence.id if silence else None,
            "silence_name": silence.name if silence else None,
            "alert_group_id": alert.group_id,
            "previous_status": previous_status,
            "new_status": new_status,
            "trigger_source": trigger_source,
        },
    )


def _pause_group_after_silencing(
    group: AlertGroup,
    *,
    silence: Silence,
    previous_status: str,
    trigger_source: str,
) -> AlertGroup:
    alerts_repo.clear_alert_group_notification(group)
    group.next_escalation_at = None
    group.updated_at = utc_now()
    group.save()

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="silenced",
        message=f"Alert silenced by active Silence: {silence.name}",
    )
    _record_transition_audit(
        action="silence.alert_applied",
        group=group,
        silence=silence,
        previous_status=previous_status,
        new_status=group.status,
        trigger_source=trigger_source,
    )
    return group


def _restart_group_after_unsilencing(
    group: AlertGroup,
    *,
    silence: Silence | None,
    previous_status: str,
    trigger_source: str,
    now: datetime,
) -> AlertGroup:
    fallback_rotation = group.route.rotation if group.route else group.rotation
    policy_rule, rotation, assignee, next_escalation_at = (
        apply_initial_escalation_policy_assignment(
            group.escalation_policy,
            fallback_rotation,
            now=now,
        )
    )

    group.escalation_rule = policy_rule
    group.rotation = rotation
    group.assignee = assignee
    group.next_escalation_at = next_escalation_at
    group.last_escalated_at = None
    group.escalation_repeat_count = 0
    group.escalation_level = 0
    group.reminder_count = 0
    group.updated_at = now
    group.save()

    if group.last_notification_at:
        alerts_repo.schedule_alert_group_notification(
            group,
            due_at=now,
            reason="reactivated",
        )
    else:
        schedule_group_notification(
            group,
            reason="notification",
            now=now,
        )

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="unsilenced",
        message=(
            f"Alert active again after Silence ended: {silence.name}"
            if silence
            else "Alert active again: no active Silence matches"
        ),
    )
    _record_transition_audit(
        action="silence.alert_reactivated",
        group=group,
        silence=silence,
        previous_status=previous_status,
        new_status=group.status,
        trigger_source=trigger_source,
    )
    return group


def record_new_alert_silences(
    alert: Alert,
    silences: list[Silence],
    *,
    now: datetime | None = None,
) -> int:
    """Persist all active Silences that matched a newly created alert."""
    now = now or utc_now()
    created = 0

    for silence in silences:
        _, was_created = silences_repo.get_or_create_application(
            silence=silence,
            alert=alert,
            previous_status="firing",
            source="new_alert",
            now=now,
        )
        created += int(was_created)

    return created


def apply_silence_to_existing_alerts(
    silence: Silence,
    *,
    now: datetime | None = None,
    trigger_source: str = "api",
) -> dict[str, int]:
    """Apply an opted-in active Silence to existing firing alerts."""
    now = now or utc_now()
    result = {"matched": 0, "silenced": 0, "groups_changed": 0}

    if not silence.apply_to_existing or not _silence_is_active(silence, now):
        return result

    alerts = list(
        Alert.select()
        .join(AlertGroup)
        .where(
            (Alert.team == silence.team_id)
            & (Alert.status.in_(("firing", "silenced")))
            & (AlertGroup.status.in_(("firing", "silenced")))
            & (AlertGroup.merged_into.is_null(True))
        )
        .order_by(Alert.id.asc())
    )
    changed_group_ids: set[int] = set()

    with database_proxy.atomic():
        for alert in alerts:
            if not _alert_matches_silence(alert, silence):
                continue

            result["matched"] += 1
            previous_status = (
                alert.status
                if alert.status in {"firing", "acknowledged"}
                else (
                    alert.previous_status
                    if alert.previous_status in {"firing", "acknowledged"}
                    else "firing"
                )
            )
            _, created = silences_repo.get_or_create_application(
                silence=silence,
                alert=alert,
                previous_status=previous_status,
                source="retroactive",
                now=now,
            )
            if not created or alert.status == "silenced":
                continue

            alert.previous_status = alert.status
            alert.status = "silenced"
            alert.silenced = True
            alert.next_escalation_at = None
            alert.save()
            alerts_repo.create_alert_event(
                alert_id=alert.id,
                group_id=alert.group_id,
                event_type="silenced",
                message=f"Retroactively matched silence: {silence.name}",
            )
            _record_alert_application_audit(
                action="silence.alert_applied",
                alert=alert,
                silence=silence,
                previous_status=previous_status,
                new_status=alert.status,
                trigger_source=trigger_source,
            )
            changed_group_ids.add(alert.group_id)
            result["silenced"] += 1

        for group_id in changed_group_ids:
            group = AlertGroup.get_by_id(group_id)
            previous_status = group.status
            group = alerts_repo.recalculate_alert_group(group)
            if previous_status == "firing" and group.status == "silenced":
                _pause_group_after_silencing(
                    group,
                    silence=silence,
                    previous_status=previous_status,
                    trigger_source=trigger_source,
                )
                result["groups_changed"] += 1

        silence.reconciled_at = now
        silence.updated_at = now
        silence.save()

    return result


def _release_application_alert(
    application: SilenceAlertApplication,
    *,
    silence: Silence,
    reason: str,
    now: datetime,
    trigger_source: str,
) -> int | None:
    alert = application.alert
    silences_repo.release_application(application, reason=reason, now=now)

    if alert.status == "resolved":
        return None

    if silences_repo.has_other_active_application(alert.id):
        return None

    if alert.status != "silenced":
        return None

    restored_status = application.previous_status
    if restored_status not in {"firing", "acknowledged"}:
        restored_status = "firing"

    previous_status = alert.status
    alert.previous_status = previous_status
    alert.status = restored_status
    alert.silenced = False
    alert.next_escalation_at = None
    alert.save()
    alerts_repo.create_alert_event(
        alert_id=alert.id,
        group_id=alert.group_id,
        event_type="unsilenced",
        message=f"Silence no longer applies: {silence.name}",
    )
    _record_alert_application_audit(
        action="silence.alert_reactivated",
        alert=alert,
        silence=silence,
        previous_status=previous_status,
        new_status=alert.status,
        trigger_source=trigger_source,
    )
    return alert.group_id


def release_silence_applications(
    silence: Silence,
    *,
    reason: str,
    now: datetime | None = None,
    trigger_source: str = "scheduler",
    applications: list[SilenceAlertApplication] | None = None,
) -> dict[str, int]:
    """Release alerts no longer covered by one Silence."""
    now = now or utc_now()
    if applications is None:
        applications = silences_repo.list_active_applications_for_silence(
            silence.id
        )
    result = {"released": 0, "reactivated": 0, "groups_changed": 0}
    changed_group_ids: set[int] = set()

    with database_proxy.atomic():
        for application in applications:
            group_id = _release_application_alert(
                application,
                silence=silence,
                reason=reason,
                now=now,
                trigger_source=trigger_source,
            )
            result["released"] += 1
            if group_id is not None:
                changed_group_ids.add(group_id)
                result["reactivated"] += 1

        for group_id in changed_group_ids:
            group = AlertGroup.get_by_id(group_id)
            previous_status = group.status
            group = alerts_repo.recalculate_alert_group(group)
            if previous_status == "silenced" and group.status == "firing":
                _restart_group_after_unsilencing(
                    group,
                    silence=silence,
                    previous_status=previous_status,
                    trigger_source=trigger_source,
                    now=now,
                )
                result["groups_changed"] += 1

        silence.reconciled_at = now
        silence.updated_at = now
        silence.save()

    return result


def reconcile_silence(
    silence: Silence,
    *,
    now: datetime | None = None,
    trigger_source: str = "api",
) -> dict[str, int]:
    """Reconcile one Silence after create, update, disable, start or expiry."""
    now = now or utc_now()

    if not _silence_is_active(silence, now):
        if silence.enabled and not silence.deleted and now < silence.starts_at:
            result = release_silence_applications(
                silence,
                reason=RELEASE_REASON_UPDATED,
                now=now,
                trigger_source=trigger_source,
            )
            silence.reconciled_at = None
            silence.updated_at = now
            silence.save()
            return result

        reason = (
            RELEASE_REASON_DISABLED
            if not silence.enabled or silence.deleted
            else RELEASE_REASON_EXPIRED
        )
        return release_silence_applications(
            silence,
            reason=reason,
            now=now,
            trigger_source=trigger_source,
        )

    # Release applications invalidated by matcher/team changes. New-alert
    # applications remain active when they still match, even if retroactive
    # application is later disabled for this Silence.
    invalid_applications = []
    for application in silences_repo.list_active_applications_for_silence(silence.id):
        alert = application.alert
        should_keep = (
            alert.team_id == silence.team_id
            and _alert_matches_silence(alert, silence)
            and (
                application.source == "new_alert"
                or silence.apply_to_existing
            )
        )
        if not should_keep:
            invalid_applications.append(application)

    if invalid_applications:
        release_silence_applications(
            silence,
            reason=RELEASE_REASON_UPDATED,
            now=now,
            trigger_source=trigger_source,
            applications=invalid_applications,
        )

    return apply_silence_to_existing_alerts(
        silence,
        now=now,
        trigger_source=trigger_source,
    )


def reconcile_orphan_silenced_alerts(
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Backfill or reactivate silenced alerts created before application tracking."""
    now = now or utc_now()
    active_application_alerts = (
        SilenceAlertApplication
        .select(SilenceAlertApplication.alert)
        .where(SilenceAlertApplication.active == True)
    )
    alerts = list(
        Alert.select()
        .join(AlertGroup)
        .where(
            (Alert.status == "silenced")
            & (AlertGroup.status != "resolved")
            & (Alert.id.not_in(active_application_alerts))
        )
        .order_by(Alert.id.asc())
    )
    result = {"backfilled": 0, "reactivated": 0, "groups_changed": 0}
    changed_group_ids: set[int] = set()

    with database_proxy.atomic():
        for alert in alerts:
            matching = find_active_silences(
                alert.team_id,
                alert,
                now=now,
            )
            if matching:
                result["backfilled"] += record_new_alert_silences(
                    alert,
                    matching,
                    now=now,
                )
                continue

            previous_status = alert.status
            alert.previous_status = previous_status
            alert.status = "firing"
            alert.silenced = False
            alert.next_escalation_at = None
            alert.save()
            alerts_repo.create_alert_event(
                alert_id=alert.id,
                group_id=alert.group_id,
                event_type="unsilenced",
                message="No active Silence matches this alert",
            )
            _record_alert_application_audit(
                action="silence.alert_reactivated",
                alert=alert,
                silence=None,
                previous_status=previous_status,
                new_status=alert.status,
                trigger_source="scheduler",
            )
            changed_group_ids.add(alert.group_id)
            result["reactivated"] += 1

        for group_id in changed_group_ids:
            group = AlertGroup.get_by_id(group_id)
            previous_status = group.status
            group = alerts_repo.recalculate_alert_group(group)
            if previous_status == "silenced" and group.status == "firing":
                _restart_group_after_unsilencing(
                    group,
                    silence=None,
                    previous_status=previous_status,
                    trigger_source="scheduler",
                    now=now,
                )
                result["groups_changed"] += 1

    return result


def process_silence_lifecycle(
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Process scheduled Silence starts and releases idempotently."""
    now = now or utc_now()
    result = {
        "silences_started": 0,
        "silences_released": 0,
        "alerts_silenced": 0,
        "alerts_reactivated": 0,
        "legacy_alerts_backfilled": 0,
    }

    orphaned = reconcile_orphan_silenced_alerts(now=now)
    result["legacy_alerts_backfilled"] = orphaned["backfilled"]
    result["alerts_reactivated"] += orphaned["reactivated"]

    for silence in silences_repo.list_due_retroactive_silences(now=now):
        applied = apply_silence_to_existing_alerts(
            silence,
            now=now,
            trigger_source="scheduler",
        )
        result["silences_started"] += 1
        result["alerts_silenced"] += applied["silenced"]

    for silence in silences_repo.list_silences_with_due_releases(now=now):
        released = release_silence_applications(
            silence,
            reason=(
                RELEASE_REASON_DISABLED
                if not silence.enabled or silence.deleted
                else RELEASE_REASON_EXPIRED
            ),
            now=now,
            trigger_source="scheduler",
        )
        result["silences_released"] += 1
        result["alerts_reactivated"] += released["reactivated"]

    return result
