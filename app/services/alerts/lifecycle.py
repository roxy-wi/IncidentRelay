import logging

from app import Config
from app.modules.common import utc_now
from app.modules.db import alerts_repo, incidents_repo
from app.services.alerts.escalation import apply_initial_escalation_policy_assignment
from app.services.alerts.explain import (
    AlertExplainTrace,
    resolve_alert_explain_trace_level,
)
from app.services.alerts.maintenance_state import (
    apply_maintenance_to_existing_alert,
    maintenance_create_kwargs,
    maybe_apply_maintenance_to_group,
    reconcile_alert_group_maintenance,
    record_maintenance_match,
    should_apply_window_to_group,
)
from app.services.alerts.notification_queue import schedule_group_notification
from app.services.alerts.priority import (
    apply_priority_resolution_to_group,
    apply_priority_to_existing_alert,
    incident_priority_create_kwargs,
    group_priority_state,
    restore_group_priority_state,
)
from app.services.incidents.priority_policies.resolver import resolve_incident_priority
from app.services.alerts.result import AlertProcessingResult
from app.services.orchestration.runtime import (
    attach_runtime_executions,
    run_event_orchestration,
    run_service_orchestration,
)
from app.services.orchestration.pending import (
    resolve_pending_event,
    store_paused_event,
)
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.maintenance import get_maintenance_decision
from app.services.notifications.delivery import notify_alert
from app.services.routing.routing import (
    build_group_key,
    find_route_for_alert,
    get_alert_group_field_value,
    get_effective_group_by,
)
from app.services.routing.service_resolution import (
    get_effective_escalation_policy,
    get_effective_route_rotation,
    resolve_alert_service,
)
from app.services.silences import find_active_silences, record_new_alert_silences
from app.services.alerts.correlation import refresh_alert_group_correlations, refresh_alert_group_correlations_safely
from app.services.business_services.impact import refresh_business_impacts_safely_for_group
from app.services.business_services.status import refresh_business_services_safely_for_technical_service

logger = logging.getLogger("oncall.alerts")

INCIDENT_KEY_GROUP_FIELDS = frozenset({"incident_key", "labels.incident_key"})


def _incoming_priority_raises_incident(group, priority_resolution):
    """Return whether the incoming child can raise effective incident priority."""

    if not group or not priority_resolution:
        return False

    if getattr(group, "priority_set_manually", False):
        return False

    if getattr(priority_resolution, "update_mode", None) == "initial_only":
        return False

    priority = getattr(priority_resolution, "priority", None)
    current_order = getattr(group, "priority_order", None)
    incoming_order = getattr(priority, "level", None)

    if current_order is None or incoming_order is None:
        return False

    return incoming_order < current_order


def _group_incident_key(group):
    """Return a stable incident_key from persisted group state when available."""

    common_labels = getattr(group, "common_labels", None) or {}
    value = common_labels.get("incident_key")

    if value not in (None, ""):
        return str(value).strip()

    # Older groups can predate common_labels snapshots. Fall back to child
    # labels only when they all agree on one non-empty incident_key.
    values = {
        str((alert.labels or {}).get("incident_key") or "").strip()
        for alert in alerts_repo.list_alerts_for_group(group.id)
    }
    values.discard("")

    if len(values) == 1:
        return next(iter(values))

    return ""


def _is_same_incident_key_group(group, alert_data, route, *, group_key_overridden=False):
    """Return whether a child belongs to an acknowledged incident_key group."""

    if group_key_overridden or not route:
        return False

    group_by = get_effective_group_by(route)

    if len(group_by) != 1 or group_by[0] not in INCIDENT_KEY_GROUP_FIELDS:
        return False

    incoming_key = get_alert_group_field_value(
        group_by[0],
        alert_data,
        route=route,
    )
    incoming_key = str(incoming_key or "").strip()

    if not incoming_key:
        return False

    return _group_incident_key(group) == incoming_key


def _should_preserve_acknowledgement(
    group,
    alert_data,
    route,
    priority_resolution,
    *,
    group_key_overridden=False,
):
    """Keep ACK sticky for the same correlated incident unless it deteriorates."""

    if _incoming_priority_raises_incident(group, priority_resolution):
        return False

    return _is_same_incident_key_group(
        group,
        alert_data,
        route,
        group_key_overridden=group_key_overridden,
    )


def _route_for_runtime(alert_data, runtime, *, current_route=None):
    if runtime is None:
        return find_route_for_alert(alert_data)

    if runtime.route_selected_by_orchestration:
        return runtime.route

    if runtime.route is None:
        return find_route_for_alert(alert_data)

    if current_route is None:
        return find_route_for_alert(alert_data)

    return current_route


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
    trace = AlertExplainTrace.start_buffered(alert_data)
    runtime = None

    try:
        runtime = run_event_orchestration(alert_data, trace=trace)
        trace.apply_level(
            resolve_alert_explain_trace_level(runtime.trace_level)
        )
        if runtime.blocked:
            return _stopped_result(
                trace=trace,
                outcome="orchestration_blocked",
                reason=runtime.reason or "Event orchestration blocked processing.",
                result={"created": False, "group_id": None, "alert_id": None},
            )
        if (
            runtime.disposition == "drop"
            and (alert_data.get("status") or "firing") != "resolved"
        ):
            trace.step(
                "orchestration",
                "orchestration_event_dropped",
                "success",
                "Event dropped by orchestration",
                runtime.disposition_reason,
            )
            result = _stopped_result(
                trace=trace,
                outcome="dropped",
                reason=runtime.disposition_reason or "Event dropped by orchestration.",
                result={"created": False, "group_id": None, "alert_id": None},
            )
            attach_runtime_executions(runtime, group=None, alert=None)
            return result
        result = _upsert_alert(alert_data, trace, runtime=runtime)
        attach_runtime_executions(runtime, group=result.group, alert=result.alert)
        return result
    except Exception as exc:
        trace.apply_level(
            resolve_alert_explain_trace_level(
                getattr(runtime, "trace_level", None) if runtime is not None else None
            )
        )
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


def _resolve_policy_assignment(
    route,
    service,
    rotation,
    maintenance_decision,
    trace,
    *,
    policy_override=None,
    orchestration_suppressed=False,
):
    policy = policy_override or get_effective_escalation_policy(route, service)

    policy_rule, rotation, assignee, next_escalation_at = (
        apply_initial_escalation_policy_assignment(policy, rotation)
    )

    if maintenance_decision.pause_escalation_only or orchestration_suppressed:
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
    notification_policy,
    assignee,
    next_escalation_at,
    group_key,
    status,
    first_seen_at,
    last_seen_at,
    silenced,
    priority_kwargs,
    maintenance_kwargs,
    orchestration_suppressed=False,
    orchestration_suppress_reason=None,
):
    return alerts_repo.create_alert_group(
        team=team.id if team else None,
        route=route.id if route else None,
        service=service.id if service else None,
        rotation=rotation.id if rotation else None,
        escalation_policy=policy.id if policy else None,
        escalation_rule=policy_rule.id if policy_rule else None,
        notification_policy=(
            notification_policy.id if notification_policy else None
        ),
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
        orchestration_suppressed=orchestration_suppressed,
        orchestration_suppress_reason=orchestration_suppress_reason,
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
    notification_policy,
    group,
):
    alert.team = team.id if team else None
    alert.route = route.id if route else None
    alert.service = service.id if service else None
    alert.rotation = rotation.id if rotation else None
    if notification_policy is not None:
        alert.notification_policy = notification_policy.id
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
    priority_resolution,
    priority_kwargs,
    maintenance_decision,
    maintenance_kwargs,
    now,
    policy_override=None,
    notification_policy_override=None,
    orchestration_suppressed=False,
    orchestration_suppress_reason=None,
):
    group = existing_alert.group or existing_group
    priority = priority_resolution.priority
    created_group = False
    trace.existing_alert_found(existing_alert, group)

    if not group:
        policy, policy_rule, rotation, assignee, next_escalation_at = (
            _resolve_policy_assignment(
                route,
                service,
                rotation,
                maintenance_decision,
                trace,
                policy_override=policy_override,
                orchestration_suppressed=orchestration_suppressed,
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
            notification_policy=notification_policy_override,
            assignee=assignee,
            next_escalation_at=next_escalation_at,
            group_key=group_key,
            status=status,
            first_seen_at=existing_alert.first_seen_at or now,
            last_seen_at=now,
            silenced=bool(existing_alert.silenced),
            priority_kwargs=priority_kwargs,
            maintenance_kwargs=maintenance_kwargs,
            orchestration_suppressed=orchestration_suppressed,
            orchestration_suppress_reason=orchestration_suppress_reason,
        )

        created_group = True
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
    priority_state_before_recalculate = group_priority_state(group)
    previous_priority_slug = (
        None
        if created_group
        else priority_state_before_recalculate["priority_slug"]
    )
    previous_priority_order = (
        None
        if created_group
        else priority_state_before_recalculate["priority_order"]
    )

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
        notification_policy=notification_policy_override,
        group=group,
    )

    if notification_policy_override is not None:
        group.notification_policy = notification_policy_override.id

    existing_alert.orchestration_suppressed = orchestration_suppressed
    existing_alert.orchestration_suppress_reason = orchestration_suppress_reason
    group.orchestration_suppressed = orchestration_suppressed
    group.orchestration_suppress_reason = orchestration_suppress_reason
    group.save()

    if maintenance_decision.pause_escalation_only or orchestration_suppressed:
        existing_alert.next_escalation_at = None
        group.next_escalation_at = None
        group.save(only=[group.__class__.next_escalation_at])

    apply_priority_to_existing_alert(existing_alert, priority)
    apply_maintenance_to_existing_alert(existing_alert, maintenance_decision)

    existing_alert.save()

    trace.alert_updated(
        existing_alert,
        group,
        previous_status=previous_status,
    )

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
    group = restore_group_priority_state(
        group,
        priority_state_before_recalculate,
    )

    if not created_group:
        group = apply_priority_resolution_to_group(
            group,
            priority_resolution,
        )

    trace.priority_applied(
        group,
        priority_resolution,
        previous_priority_slug=previous_priority_slug,
        previous_priority_order=previous_priority_order,
        created_group=created_group,
    )

    refresh_alert_group_correlations_safely(group, reason="existing_alert_update")

    if getattr(group, "service_id", None):
        refresh_business_services_safely_for_technical_service(group.service_id, reason="existing_alert_update")

    refresh_business_impacts_safely_for_group(group, reason="existing_alert_update")

    if orchestration_suppressed:
        alerts_repo.clear_alert_group_notification(group)
        trace.step(
            "orchestration",
            "orchestration_notifications_suppressed",
            "success",
            "Notifications suppressed by orchestration",
            orchestration_suppress_reason,
        )
    elif maintenance_decision.suppress_notifications:
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


def _upsert_alert(alert_data, trace, runtime=None):
    route = _route_for_runtime(alert_data, runtime)

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
    service = (
        runtime.service
        if runtime and runtime.service
        else resolve_alert_service(route, alert_data)
    )

    if runtime is not None and service is not None:
        runtime = run_service_orchestration(
            alert_data,
            runtime,
            route=route,
            team=team,
            service=service,
            trace=trace,
        )

        if runtime.blocked:
            return _stopped_result(
                trace=trace,
                outcome="orchestration_blocked",
                reason=runtime.reason or "Service orchestration blocked processing.",
                result={"created": False, "group_id": None, "alert_id": None},
            )

        route = _route_for_runtime(
            alert_data,
            runtime,
            current_route=route,
        )

        if not route:
            trace.route_not_matched(alert_data)

            return _stopped_result(
                trace=trace,
                outcome="routing_failed",
                reason="Service orchestration did not leave an active route.",
                result={"created": False, "group_id": None, "alert_id": None},
            )
        team = route.team
        service = (
            runtime.service
            if runtime.service
            else resolve_alert_service(route, alert_data)
        )

    rotation = get_effective_route_rotation(route, service)

    trace.route_matched(route, team)
    trace.service_resolved(service)
    trace.rotation_resolved(rotation)

    status = alert_data.get("status") or "firing"
    group_id = getattr(getattr(route, "team", None), "group_id", None)

    if status == "resolved" and group_id is not None:
        pending = resolve_pending_event(
            group_id=group_id,
            source=alert_data.get("source"),
            dedup_key=alert_data.get("dedup_key"),
            trace=trace,
        )
        if pending is not None:
            return _stopped_result(
                trace=trace,
                outcome="resolved_before_activation",
                reason="Paused event resolved before activation.",
                result={
                    "created": False,
                    "group_id": None,
                    "alert_id": None,
                    "pending_event_id": pending.id,
                },
            )

    if runtime is not None and runtime.disposition == "drop":
        trace.step(
            "orchestration",
            "orchestration_event_dropped",
            "success",
            "Event dropped by orchestration",
            runtime.disposition_reason,
        )
        return _stopped_result(
            trace=trace,
            outcome="dropped",
            reason=runtime.disposition_reason or "Event dropped by orchestration.",
            result={"created": False, "group_id": None, "alert_id": None},
        )

    if runtime is not None and runtime.disposition == "pause":
        pending = store_paused_event(
            alert_data,
            runtime,
            route=route,
            service=service,
            trace=trace,
        )
        return _stopped_result(
            trace=trace,
            outcome="paused",
            reason=runtime.disposition_reason or "Event activation paused by orchestration.",
            result={
                "created": False,
                "group_id": None,
                "alert_id": None,
                "pending_event_id": pending.id,
                "activation_at": pending.activation_at.isoformat(),
            },
        )

    orchestration_suppressed = bool(
        runtime is not None and runtime.disposition == "suppress"
    )
    orchestration_suppress_reason = (
        runtime.disposition_reason if orchestration_suppressed else None
    )

    priority_resolution = resolve_incident_priority(
        alert_data,
        team=team,
        route=route,
        service=service,
    )
    priority = priority_resolution.priority
    priority_kwargs = incident_priority_create_kwargs(priority)

    trace.priority_resolution_resolved(
        priority_resolution,
        severity=alert_data.get("severity"),
    )

    group_key = (
        runtime.group_key
        if runtime and runtime.group_key
        else build_group_key(route, alert_data, service=service)
    )

    trace.group_key_built(group_key)

    now = utc_now()

    maintenance_decision = get_maintenance_decision(
        team=team,
        route=route,
        service=service,
        status=status,
        now=now,
    )

    maintenance_incident_status = maintenance_decision.incident_status
    maintenance_kwargs = maintenance_create_kwargs(maintenance_decision)

    trace.maintenance_resolved(maintenance_decision)

    grouping_window_seconds = (
        runtime.grouping_window_seconds
        if runtime and runtime.grouping_window_seconds is not None
        else Config.ALERT_GROUP_WINDOW_SECONDS
    )
    existing_alert = alerts_repo.find_existing_alert(
        alert_data["source"],
        alert_data["dedup_key"],
        grouping_window_seconds,
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

    target_group = existing_alert.group if existing_alert and existing_alert.group else existing_group
    if target_group and maintenance_decision.window and not should_apply_window_to_group(
        maintenance_decision.window,
        target_group,
        now=now,
    ):
        from app.services.maintenance import MaintenanceDecision
        maintenance_decision = MaintenanceDecision()
        maintenance_kwargs = {}
        maintenance_incident_status = None

    if maintenance_incident_status:
        status = maintenance_incident_status

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
            priority_resolution=priority_resolution,
            priority_kwargs=priority_kwargs,
            maintenance_decision=maintenance_decision,
            maintenance_kwargs=maintenance_kwargs,
            now=now,
            policy_override=(runtime.escalation_policy if runtime else None),
            notification_policy_override=(
                runtime.notification_policy if runtime else None
            ),
            orchestration_suppressed=orchestration_suppressed,
            orchestration_suppress_reason=orchestration_suppress_reason,
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
            policy_override=(runtime.escalation_policy if runtime else None),
            orchestration_suppressed=orchestration_suppressed,
        )
    )

    silences = find_active_silences(
        team.id if team else None,
        alert_data,
        now=now,
    )
    silence = silences[0] if silences else None

    trace.silence_resolved(silence)

    if silences and status == "firing":
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
            notification_policy=(runtime.notification_policy if runtime else None),
            assignee=assignee,
            next_escalation_at=next_escalation_at,
            group_key=group_key,
            status=status,
            first_seen_at=now,
            last_seen_at=now,
            silenced=bool(silence),
            priority_kwargs=priority_kwargs,
            maintenance_kwargs=maintenance_kwargs,
            orchestration_suppressed=orchestration_suppressed,
            orchestration_suppress_reason=orchestration_suppress_reason,
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
        preserve_ack = _should_preserve_acknowledgement(
            group,
            alert_data,
            route,
            priority_resolution,
            group_key_overridden=bool(runtime and runtime.group_key),
        )

        if preserve_ack:
            trace.step(
                "grouping",
                "acknowledgement_preserved",
                "success",
                "Acknowledgement preserved",
                (
                    "Correlated child matched the acknowledged incident_key "
                    "without increasing effective incident priority."
                ),
                incident_key=_group_incident_key(group),
                priority_slug=getattr(group, "priority_slug", None),
            )
            trace.group_reused(group)
        else:
            priority_increased = _incoming_priority_raises_incident(
                group,
                priority_resolution,
            )

            group.previous_status = group.status
            group.status = "firing"
            group.acknowledged_by = None
            group.acknowledged_at = None

            if priority_increased:
                # A material deterioration starts a fresh escalation cycle.
                # Reusing a pre-ACK due time could immediately jump to a later
                # escalation step after the incident is reopened.
                group.escalation_policy = policy
                group.escalation_rule = policy_rule
                group.rotation = rotation
                group.assignee = assignee
                group.next_escalation_at = next_escalation_at
                group.last_escalated_at = None
                group.escalation_level = 0
                group.escalation_repeat_count = 0
                group.reminder_count = 0

            group.updated_at = now
            group.save()

            trace.group_reopened(group)

            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type="reopened",
                message="New alert requires reopening acknowledged incident",
            )
    else:
        trace.group_reused(group)

    group.orchestration_suppressed = orchestration_suppressed
    group.orchestration_suppress_reason = orchestration_suppress_reason
    group_fields = [
        group.__class__.orchestration_suppressed,
        group.__class__.orchestration_suppress_reason,
    ]
    if orchestration_suppressed:
        group.next_escalation_at = None
        group_fields.append(group.__class__.next_escalation_at)
    if runtime is not None and runtime.notification_policy is not None:
        group.notification_policy = runtime.notification_policy.id
        group_fields.append(group.__class__.notification_policy)
    group.save(only=group_fields)

    priority_state_before_recalculate = group_priority_state(group)

    previous_priority_slug = (
        None
        if created_group
        else priority_state_before_recalculate["priority_slug"]
    )
    previous_priority_order = (
        None
        if created_group
        else priority_state_before_recalculate["priority_order"]
    )

    maybe_apply_maintenance_to_group(group, maintenance_decision)

    alert = alerts_repo.create_alert(
        group=group.id,
        team=team.id if team else None,
        route=route.id if route else None,
        service=service.id if service else None,
        rotation=rotation.id if rotation else None,
        escalation_policy=policy.id if policy else None,
        escalation_rule=policy_rule.id if policy_rule else None,
        notification_policy=(
            runtime.notification_policy.id
            if runtime and runtime.notification_policy
            else getattr(group, "notification_policy_id", None)
        ),
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
        orchestration_suppressed=orchestration_suppressed,
        orchestration_suppress_reason=orchestration_suppress_reason,
        **priority_kwargs,
        **maintenance_kwargs,
    )

    trace.alert_created(alert, group)

    if silences:
        record_new_alert_silences(alert, silences, now=now)

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

    reconcile_alert_group_maintenance(
        group,
        now=now,
        trigger_source="intake",
    )

    if alert_data.get("routing_error"):
        alerts_repo.create_alert_event(
            alert_id=alert.id,
            group_id=group.id,
            event_type="routing_error",
            message=alert_data["routing_error"],
        )

        trace.routing_warning_recorded(alert_data["routing_error"])

    for matched_silence in silences:
        alerts_repo.create_alert_event(
            alert_id=alert.id,
            group_id=group.id,
            event_type="silenced",
            message=f"Matched silence: {matched_silence.name}",
        )

    group = alerts_repo.recalculate_alert_group(group)
    group = restore_group_priority_state(
        group,
        priority_state_before_recalculate,
    )

    if not created_group:
        group = apply_priority_resolution_to_group(
            group,
            priority_resolution,
        )

    trace.priority_applied(
        group,
        priority_resolution,
        previous_priority_slug=None if created_group else previous_priority_slug,
        previous_priority_order=None if created_group else previous_priority_order,
        created_group=created_group,
    )

    refresh_alert_group_correlations_safely(group, reason="new_alert")

    if getattr(group, "service_id", None):
        refresh_business_services_safely_for_technical_service(group.service_id, reason="new_alert")

    refresh_business_impacts_safely_for_group(group, reason="new_alert")

    if alert_data["source"] == "sentry":
        labels = alert_data.get("labels") or {}

        logger.info(
            "sentry source event link debug",
            extra={
                "extra": {
                    "event_type": "sentry_source_event_link_debug",
                    "title": alert_data.get("title"),
                    "external_id": alert_data.get("external_id"),
                    "dedup_key": alert_data.get("dedup_key"),
                    "group_key": group_key,
                    "route_id": route.id if route else None,
                    "team_name": team.name if team else None,
                    "team_id": team.id if team else None,
                    "service_id": service.id if service else None,
                    "event_link": labels.get("event_link") or "",
                    "sentry_url": labels.get("sentry_url") or "",
                    "issue_id": labels.get("issue_id") or "",
                    "event_id": labels.get("event_id") or "",
                    "sentry_alert_id": labels.get("sentry_alert_id") or "",
                    "project_slug": labels.get("project_slug") or "",
                    "organization_slug": labels.get("organization_slug") or "",
                    "label_keys": sorted(labels.keys()),
                }
            },
        )

    try:
        refresh_alert_group_correlations(group)
    except Exception:
        logger.exception(
            "alert group correlation refresh failed",
            extra={
                "extra": {
                    "alert_group_id": getattr(group, "id", None),
                    "service_id": getattr(group, "service_id", None),
                }
            },
        )

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

    if orchestration_suppressed:
        alerts_repo.clear_alert_group_notification(group)
        trace.step(
            "orchestration",
            "orchestration_notifications_suppressed",
            "success",
            "Notifications suppressed by orchestration",
            orchestration_suppress_reason,
        )
    elif (
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
