import logging
from datetime import datetime

from app import Config
from app.modules.db import alerts_repo, incidents_repo
from app.services.alerts.escalation import apply_initial_escalation_policy_assignment
from app.services.alerts.explain import AlertExplainTrace
from app.services.alerts.maintenance_state import (
    apply_maintenance_to_existing_alert,
    maintenance_create_kwargs,
    maybe_apply_maintenance_to_group,
    record_maintenance_match,
)
from app.services.alerts.notification_queue import schedule_group_notification
from app.services.alerts.priority import (
    apply_priority_to_existing_alert,
    incident_priority_create_kwargs,
    incident_priority_from_alert,
    maybe_apply_auto_priority_to_group,
)
from app.services.alerts.result import AlertProcessingResult
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.maintenance import get_maintenance_decision
from app.services.notifications.delivery import notify_alert
from app.services.routing.routing import build_group_key, find_route_for_alert
from app.services.routing.service_resolution import (
    get_effective_escalation_policy,
    get_effective_route_rotation,
    resolve_alert_service,
)
from app.services.silences import find_active_silence

logger = logging.getLogger("oncall.alerts")


def _add_service_stakeholders_for_new_group(group):
    """Auto-add service stakeholders to a newly created incident."""
    try:
        stakeholders = incidents_repo.add_service_stakeholders_to_incident(group)

        if stakeholders:
            notify_stakeholders(group, "created")
    except Exception as exc:
        logger.exception(
            "failed to auto-add service stakeholders to incident",
            extra={
                "extra": {
                    "alert_group_id": getattr(group, "id", None),
                    "service_id": getattr(group, "service_id", None),
                    "error": str(exc),
                }
            },
        )


def upsert_alert(alert_data):
    """Create/update concrete alert and attach it to an incident.

    Return:
        AlertProcessingResult
    """
    trace = AlertExplainTrace.start(alert_data)

    try:
        return _upsert_alert(alert_data, trace)
    except Exception as exc:
        trace.fail(exc)
        raise


def _stopped_result(*, trace, outcome, reason, result=None):
    trace.stopped(
        outcome=outcome,
        reason=reason,
        result=result or {},
    )

    return AlertProcessingResult(
        group=None,
        alert=None,
        created_group=False,
        outcome=outcome,
        processing_status="stopped",
        reason=reason,
        trace=trace,
    )


def _completed_result(*, trace, group, alert, created_group, outcome):
    return AlertProcessingResult(
        group=group,
        alert=alert,
        created_group=created_group,
        outcome=outcome,
        processing_status="completed",
        trace=trace,
    )


def _resolve_policy_assignment(route, service, rotation, maintenance_decision, trace):
    policy = get_effective_escalation_policy(route, service)

    policy_rule, rotation, assignee, next_escalation_at = (
        apply_initial_escalation_policy_assignment(policy, rotation)
    )

    if maintenance_decision.pause_escalation_only:
        next_escalation_at = None

    trace.policy_resolved(policy, policy_rule)
    trace.assignee_resolved(
        assignee,
        rotation=rotation,
        next_escalation_at=next_escalation_at,
    )

    return policy, policy_rule, rotation, assignee, next_escalation_at


def _create_group(
    *,
    alert_data,
    route,
    team,
    service,
    rotation,
    policy,
    policy_rule,
    assignee,
    next_escalation_at,
    group_key,
    status,
    first_seen_at,
    last_seen_at,
    silenced,
    priority_kwargs,
    maintenance_kwargs,
):
    return alerts_repo.create_alert_group(
        team=team.id if team else None,
        route=route.id if route else None,
        service=service.id if service else None,
        rotation=rotation.id if rotation else None,
        escalation_policy=policy.id if policy else None,
        escalation_rule=policy_rule.id if policy_rule else None,
        next_escalation_at=next_escalation_at,
        assignee=assignee.id if assignee else None,
        source=alert_data["source"],
        group_key=group_key,
        title=alert_data["title"],
        message=alert_data.get("message"),
        severity=alert_data.get("severity"),
        status=status,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        silenced=silenced,
        priority_set_manually=False,
        **priority_kwargs,
        **maintenance_kwargs,
    )


def _set_alert_routing_fields(
    alert,
    *,
    team,
    route,
    service,
    rotation,
    group,
):
    alert.team = team.id if team else None
    alert.route = route.id if route else None
    alert.service = service.id if service else None
    alert.rotation = rotation.id if rotation else None
    alert.group = group.id


def _handle_existing_alert(
    *,
    alert_data,
    trace,
    existing_alert,
    existing_group,
    route,
    team,
    service,
    rotation,
    status,
    group_key,
    priority,
    priority_kwargs,
    maintenance_decision,
    maintenance_kwargs,
    now,
):
    group = existing_alert.group or existing_group
    trace.existing_alert_found(existing_alert, group)

    if not group:
        policy, policy_rule, rotation, assignee, next_escalation_at = (
            _resolve_policy_assignment(
                route,
                service,
                rotation,
                maintenance_decision,
                trace,
            )
        )

        group = _create_group(
            alert_data=alert_data,
            route=route,
            team=team,
            service=service,
            rotation=rotation,
            policy=policy,
            policy_rule=policy_rule,
            assignee=assignee,
            next_escalation_at=next_escalation_at,
            group_key=group_key,
            status=status,
            first_seen_at=existing_alert.first_seen_at or now,
            last_seen_at=now,
            silenced=bool(existing_alert.silenced),
            priority_kwargs=priority_kwargs,
            maintenance_kwargs=maintenance_kwargs,
        )

        trace.group_created_for_existing_alert(group, existing_alert)

        _add_service_stakeholders_for_new_group(group)

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="created",
            message="Incident created for existing alert",
        )

        record_maintenance_match(
            group,
            maintenance_decision,
        )
    else:
        trace.group_reused(group)

    old_group_status = group.status

    existing_alert, previous_status = alerts_repo.update_alert_from_payload(
        existing_alert,
        alert_data,
        status,
        group_key,
    )

    _set_alert_routing_fields(
        existing_alert,
        team=team,
        route=route,
        service=service,
        rotation=rotation,
        group=group,
    )

    if maintenance_decision.pause_escalation_only:
        existing_alert.next_escalation_at = None

    apply_priority_to_existing_alert(existing_alert, priority)
    apply_maintenance_to_existing_alert(existing_alert, maintenance_decision)

    existing_alert.save()

    trace.alert_updated(
        existing_alert,
        group,
        previous_status=previous_status,
    )

    maybe_apply_auto_priority_to_group(group, priority)
    maybe_apply_maintenance_to_group(group, maintenance_decision)

    if maintenance_decision.matched:
        record_maintenance_match(
            group,
            maintenance_decision,
            alert_id=existing_alert.id,
        )

    if status == "resolved" and previous_status != "resolved":
        alerts_repo.create_alert_event(
            alert_id=existing_alert.id,
            group_id=group.id,
            event_type="resolved",
            message="Alert resolved by incoming payload",
        )
        trace.alert_resolved(existing_alert, group)
    else:
        alerts_repo.create_alert_event(
            alert_id=existing_alert.id,
            group_id=group.id,
            event_type="updated",
            message="Alert updated from incoming payload",
        )

    group = alerts_repo.recalculate_alert_group(group)

    if maintenance_decision.suppress_notifications:
        alerts_repo.clear_alert_group_notification(group)
        trace.notification_suppressed(
            behavior=maintenance_decision.behavior,
        )
    elif status == "resolved":
        if group.status == "resolved":
            alerts_repo.clear_alert_group_notification(group)

            if old_group_status != "resolved":
                notify_stakeholders(
                    group,
                    "resolved",
                    old_value=old_group_status,
                )

            if group.last_notification_at:
                sent_count = notify_alert(
                    group,
                    event_type="resolved",
                )
                trace.resolved_notification_sent(sent_count=sent_count)
            else:
                trace.notification_not_needed(group)
        elif group.status == "firing":
            schedule_group_notification(
                group,
                reason="update",
                now=now,
            )
            trace.notification_scheduled(reason="update")
        else:
            trace.notification_not_needed(group)
    elif group.status == "firing":
        schedule_group_notification(
            group,
            reason="update",
            now=now,
        )
        trace.notification_scheduled(reason="update")
    else:
        trace.notification_not_needed(group)

    trace.updated(
        group=group,
        alert=existing_alert,
    )

    return _completed_result(
        trace=trace,
        group=group,
        alert=existing_alert,
        created_group=False,
        outcome="updated",
    )


def _upsert_alert(alert_data, trace):
    route = find_route_for_alert(alert_data)

    if not route:
        trace.route_not_matched(alert_data)

        logger.warning(
            "alert routing failed",
            extra={
                "extra": {
                    "source": alert_data.get("source"),
                    "dedup_key": alert_data.get("dedup_key"),
                    "team_slug": alert_data.get("team_slug"),
                    "routing_error": alert_data.get("routing_error"),
                    "trace_id": trace.trace_id,
                }
            },
        )

        return _stopped_result(
            trace=trace,
            outcome="routing_failed",
            reason="Alert did not match any active route.",
            result={
                "created": False,
                "group_id": None,
                "alert_id": None,
            },
        )

    team = route.team
    service = resolve_alert_service(route, alert_data)
    rotation = get_effective_route_rotation(route, service)

    trace.route_matched(route, team)
    trace.service_resolved(service)
    trace.rotation_resolved(rotation)

    status = alert_data.get("status") or "firing"

    priority = incident_priority_from_alert(alert_data)
    priority_kwargs = incident_priority_create_kwargs(priority)

    trace.priority_resolved(
        priority,
        severity=alert_data.get("severity"),
    )

    group_key = build_group_key(
        route,
        alert_data,
        service=service,
    )

    trace.group_key_built(group_key)

    now = datetime.utcnow()

    maintenance_decision = get_maintenance_decision(
        team=team,
        route=route,
        service=service,
        status=status,
        now=now,
    )

    if maintenance_decision.incident_status:
        status = maintenance_decision.incident_status

    maintenance_kwargs = maintenance_create_kwargs(maintenance_decision)

    trace.maintenance_resolved(maintenance_decision)

    existing_alert = alerts_repo.find_existing_alert(
        alert_data["source"],
        alert_data["dedup_key"],
        Config.ALERT_GROUP_WINDOW_SECONDS,
    )

    existing_group = alerts_repo.find_open_alert_group(
        source=alert_data["source"],
        group_key=group_key,
        team_id=team.id if team else None,
        route_id=route.id if route else None,
        service_id=service.id if service else None,
    )

    trace.dedup_completed(
        existing_alert=existing_alert,
        existing_group=existing_group,
    )

    if maintenance_decision.suppress_incident and not existing_alert and not existing_group:
        trace.incident_suppressed(maintenance_decision)

        return _stopped_result(
            trace=trace,
            outcome="suppressed",
            reason="Incident suppressed by maintenance.",
            result={
                "created": False,
                "group_id": None,
                "alert_id": None,
                "maintenance_window_id": (
                    maintenance_decision.window.id
                    if maintenance_decision.window
                    else None
                ),
            },
        )

    if existing_alert:
        return _handle_existing_alert(
            alert_data=alert_data,
            trace=trace,
            existing_alert=existing_alert,
            existing_group=existing_group,
            route=route,
            team=team,
            service=service,
            rotation=rotation,
            status=status,
            group_key=group_key,
            priority=priority,
            priority_kwargs=priority_kwargs,
            maintenance_decision=maintenance_decision,
            maintenance_kwargs=maintenance_kwargs,
            now=now,
        )

    if status == "resolved":
        trace.orphan_resolved_ignored(alert_data)

        logger.info(
            "orphan resolved alert ignored",
            extra={
                "extra": {
                    "source": alert_data["source"],
                    "dedup_key": alert_data["dedup_key"],
                    "title": alert_data.get("title"),
                    "trace_id": trace.trace_id,
                }
            },
        )

        return _stopped_result(
            trace=trace,
            outcome="ignored",
            reason="Resolved payload did not match an existing active alert.",
            result={
                "created": False,
                "group_id": None,
                "alert_id": None,
            },
        )

    policy, policy_rule, rotation, assignee, next_escalation_at = (
        _resolve_policy_assignment(
            route,
            service,
            rotation,
            maintenance_decision,
            trace,
        )
    )

    silence = find_active_silence(
        team.id if team else None,
        alert_data,
    )

    trace.silence_resolved(silence)

    if silence and status == "firing":
        status = "silenced"

    group = existing_group
    created_group = False

    if not group:
        group = _create_group(
            alert_data=alert_data,
            route=route,
            team=team,
            service=service,
            rotation=rotation,
            policy=policy,
            policy_rule=policy_rule,
            assignee=assignee,
            next_escalation_at=next_escalation_at,
            group_key=group_key,
            status=status,
            first_seen_at=now,
            last_seen_at=now,
            silenced=bool(silence),
            priority_kwargs=priority_kwargs,
            maintenance_kwargs=maintenance_kwargs,
        )

        created_group = True
        trace.group_created(group)

        _add_service_stakeholders_for_new_group(group)

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="created",
            message="Incident created",
        )

        record_maintenance_match(
            group,
            maintenance_decision,
        )
    elif group.status == "acknowledged" and status == "firing":
        group.previous_status = group.status
        group.status = "firing"
        group.acknowledged_by = None
        group.acknowledged_at = None
        group.updated_at = now
        group.save()

        trace.group_reopened(group)

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="reopened",
            message="New alert received in acknowledged incident",
        )
    else:
        trace.group_reused(group)

    maybe_apply_auto_priority_to_group(group, priority)
    maybe_apply_maintenance_to_group(group, maintenance_decision)

    alert = alerts_repo.create_alert(
        group=group.id,
        team=team.id if team else None,
        route=route.id if route else None,
        service=service.id if service else None,
        rotation=rotation.id if rotation else None,
        escalation_policy=policy.id if policy else None,
        escalation_rule=policy_rule.id if policy_rule else None,
        next_escalation_at=next_escalation_at,
        assignee=assignee.id if assignee else None,
        source=alert_data["source"],
        external_id=alert_data.get("external_id"),
        dedup_key=alert_data["dedup_key"],
        group_key=group_key,
        title=alert_data["title"],
        message=alert_data.get("message"),
        severity=alert_data.get("severity"),
        labels=alert_data.get("labels"),
        payload=alert_data.get("payload"),
        status=status,
        first_seen_at=now,
        last_seen_at=now,
        silenced=bool(silence),
        **priority_kwargs,
        **maintenance_kwargs,
    )

    trace.alert_created(alert, group)

    alerts_repo.create_alert_event(
        alert_id=alert.id,
        group_id=group.id,
        event_type="created",
        message="Alert created",
    )

    if maintenance_decision.matched:
        record_maintenance_match(
            group,
            maintenance_decision,
            alert_id=alert.id,
        )

    if alert_data.get("routing_error"):
        alerts_repo.create_alert_event(
            alert_id=alert.id,
            group_id=group.id,
            event_type="routing_error",
            message=alert_data["routing_error"],
        )

        trace.routing_warning_recorded(alert_data["routing_error"])

    if silence:
        alerts_repo.create_alert_event(
            alert_id=alert.id,
            group_id=group.id,
            event_type="silenced",
            message=f"Matched silence: {silence.name}",
        )

    group = alerts_repo.recalculate_alert_group(group)

    logger.info(
        "alert added to incident",
        extra={
            "extra": {
                "alert_id": alert.id,
                "alert_group_id": group.id,
                "incident_id": group.id,
                "team": group.team.slug if group.team else None,
                "route_id": group.route.id if group.route else None,
                "service_id": service.id if service else None,
                "created_group": created_group,
                "group_key": group.group_key,
                "priority": group.priority_slug,
                "maintenance_window_id": group.maintenance_window_id,
                "maintenance_behavior": group.maintenance_behavior,
                "maintenance_suppressed": group.maintenance_suppressed,
                "trace_id": trace.trace_id,
            }
        },
    )

    if (
        status == "firing"
        and group.status == "firing"
        and not maintenance_decision.suppress_notifications
    ):
        schedule_group_notification(
            group,
            reason="notification" if created_group else "update",
            now=now,
        )

        trace.notification_scheduled(
            reason="notification" if created_group else "update",
        )
    elif maintenance_decision.suppress_notifications:
        alerts_repo.clear_alert_group_notification(group)

        trace.notification_suppressed(
            behavior=maintenance_decision.behavior,
        )
    elif group.status != "firing":
        alerts_repo.clear_alert_group_notification(group)

        trace.notification_not_needed(group)
    else:
        trace.notification_not_needed(group)

    outcome = "created" if created_group else "added"

    trace.processed(
        group=group,
        alert=alert,
        created_group=created_group,
        outcome=outcome,
    )

    return _completed_result(
        trace=trace,
        group=group,
        alert=alert,
        created_group=created_group,
        outcome=outcome,
    )
