import logging
from datetime import datetime

from app import Config
from app.modules.db import incidents_repo, alerts_repo
from app.services.alerts.escalation import apply_initial_escalation_policy_assignment
from app.services.alerts.maintenance_state import maintenance_create_kwargs, record_maintenance_match, \
    apply_maintenance_to_existing_alert, maybe_apply_maintenance_to_group
from app.services.alerts.notification_queue import schedule_group_notification
from app.services.alerts.priority import incident_priority_from_alert, incident_priority_create_kwargs, \
    apply_priority_to_existing_alert, maybe_apply_auto_priority_to_group
from app.services.maintenance import get_maintenance_decision
from app.services.notifications.delivery import notify_alert
from app.services.routing.routing import find_route_for_alert, build_group_key
from app.services.routing.service_resolution import get_effective_escalation_policy, resolve_alert_service, \
    get_effective_route_rotation
from app.services.silences import find_active_silence

logger = logging.getLogger("oncall.alerts")


def _add_service_stakeholders_for_new_group(group):
    """Auto-add service stakeholders to a newly created incident."""
    try:
        incidents_repo.add_service_stakeholders_to_incident(group)
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


def _create_group_for_alert(alert_data, route, team, service, rotation, group_key, status):
    policy = get_effective_escalation_policy(route, service) if route else None

    policy_rule, rotation, assignee, next_escalation_at = (
        apply_initial_escalation_policy_assignment(policy, rotation)
    )

    priority = incident_priority_from_alert(alert_data)
    priority_kwargs = incident_priority_create_kwargs(priority)

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
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        priority_set_manually=False,
        **priority_kwargs,
    )


def upsert_alert(alert_data):
    """
    Create/update concrete alert and attach it to an incident.

    Return:
        tuple[AlertGroup | None, bool]:
        - group object or None
        - True if a new group was created, False otherwise
    """
    route = find_route_for_alert(alert_data)

    if not route:
        logger.warning(
            "alert routing failed",
            extra={
                "extra": {
                    "source": alert_data.get("source"),
                    "dedup_key": alert_data.get("dedup_key"),
                    "team_slug": alert_data.get("team_slug"),
                    "routing_error": alert_data.get("routing_error"),
                }
            },
        )
        return None, False

    team = route.team
    service = resolve_alert_service(route, alert_data)
    rotation = get_effective_route_rotation(route, service)

    status = alert_data.get("status") or "firing"

    priority = incident_priority_from_alert(alert_data)
    priority_kwargs = incident_priority_create_kwargs(priority)

    group_key = build_group_key(
        route,
        alert_data,
        service=service,
    )

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

    maintenance_kwargs = maintenance_create_kwargs(
        maintenance_decision,
    )

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

    if maintenance_decision.suppress_incident and not existing_alert and not existing_group:
        logger.info(
            "alert suppressed by maintenance window",
            extra={
                "extra": {
                    "source": alert_data["source"],
                    "dedup_key": alert_data["dedup_key"],
                    "group_key": group_key,
                    "team_id": team.id if team else None,
                    "route_id": route.id if route else None,
                    "service_id": service.id if service else None,
                    "maintenance_window_id": maintenance_decision.window.id
                    if maintenance_decision.window
                    else None,
                    "maintenance_behavior": maintenance_decision.behavior,
                }
            },
        )
        return None, False

    # Existing concrete alert: this is dedup/update, not a new child alert.
    # Do not reopen acknowledged group just because the same alert was updated.
    if existing_alert:
        group = existing_alert.group or existing_group

        if not group:
            policy = get_effective_escalation_policy(route, service)

            policy_rule, rotation, assignee, next_escalation_at = (
                apply_initial_escalation_policy_assignment(policy, rotation)
            )

            if maintenance_decision.pause_escalation_only:
                next_escalation_at = None

            group = alerts_repo.create_alert_group(
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
                first_seen_at=existing_alert.first_seen_at or now,
                last_seen_at=now,
                silenced=bool(existing_alert.silenced),
                priority_set_manually=False,
                **priority_kwargs,
                **maintenance_kwargs,
            )

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

        existing_alert, previous_status = alerts_repo.update_alert_from_payload(
            existing_alert,
            alert_data,
            status,
            group_key,
        )

        existing_alert.team = team.id if team else None
        existing_alert.route = route.id if route else None
        existing_alert.service = service.id if service else None
        existing_alert.rotation = rotation.id if rotation else None
        existing_alert.group = group.id

        if maintenance_decision.pause_escalation_only:
            existing_alert.next_escalation_at = None

        apply_priority_to_existing_alert(existing_alert, priority)
        apply_maintenance_to_existing_alert(existing_alert, maintenance_decision)

        existing_alert.save()

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

        elif status == "resolved":
            if group.status == "resolved":
                alerts_repo.clear_alert_group_notification(group)

                if group.last_notification_at:
                    notify_alert(group, event_type="resolved")

            elif group.status == "firing":
                schedule_group_notification(
                    group,
                    reason="update",
                    now=now,
                )

        else:
            if group.status == "firing":
                schedule_group_notification(
                    group,
                    reason="update",
                    now=now,
                )

        return group, False

    # Do not create a new active alert/group from an orphan resolved payload.
    if status == "resolved":
        logger.info(
            "orphan resolved alert ignored",
            extra={
                "extra": {
                    "source": alert_data["source"],
                    "dedup_key": alert_data["dedup_key"],
                    "title": alert_data.get("title"),
                }
            },
        )
        return None, False

    policy = get_effective_escalation_policy(route, service)

    policy_rule, rotation, assignee, next_escalation_at = (
        apply_initial_escalation_policy_assignment(policy, rotation)
    )

    if maintenance_decision.pause_escalation_only:
        next_escalation_at = None

    silence = find_active_silence(team.id if team else None, alert_data)

    if silence and status == "firing":
        status = "silenced"

    group = existing_group
    created_group = False

    if not group:
        group = alerts_repo.create_alert_group(
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
            first_seen_at=now,
            last_seen_at=now,
            silenced=bool(silence),
            priority_set_manually=False,
            **priority_kwargs,
            **maintenance_kwargs,
        )

        created_group = True

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
        # This is a new child alert inside an existing acknowledged group.
        # A new signal must make the incident visible again.
        group.previous_status = group.status
        group.status = "firing"
        group.acknowledged_by = None
        group.acknowledged_at = None
        group.updated_at = now
        group.save()

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="reopened",
            message="New alert received in acknowledged incident",
        )

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

    elif maintenance_decision.suppress_notifications:
        alerts_repo.clear_alert_group_notification(group)

    elif group.status != "firing":
        alerts_repo.clear_alert_group_notification(group)

    return group, created_group
