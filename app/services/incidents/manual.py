from uuid import uuid4

from app.db import database_proxy
from app.modules.db import alerts_repo, incidents_repo
from app.modules.db.models import Service, Team
from app.services.alerts.escalation import apply_initial_escalation_policy_assignment
from app.services.alerts.notification_queue import schedule_group_notification
from app.services.alerts.priority import incident_priority_create_kwargs, incident_priority_from_alert
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.routing.service_resolution import get_effective_escalation_policy, get_effective_route_rotation
from app.modules.common import utc_now


def _get_manual_incident_team(team_id):
    team = Team.get_or_none(
        (Team.id == team_id)
        & (Team.deleted == False)  # noqa: E712
    )

    if not team:
        raise LookupError("team not found")

    return team


def _get_manual_incident_service(service_id, team_id):
    if not service_id:
        return None

    service = Service.get_or_none(
        (Service.id == service_id)
        & (Service.deleted == False)  # noqa: E712
    )

    if not service:
        raise LookupError("service not found")

    if service.team_id != team_id:
        raise ValueError("service does not belong to selected team")

    return service


def _add_service_stakeholders_for_manual_incident(group):
    try:
        stakeholders = incidents_repo.add_service_stakeholders_to_incident(group)

        if stakeholders:
            notify_stakeholders(group, "created")
    except Exception:
        # Do not fail incident creation because stakeholder copy/notify failed.
        pass


def create_manual_incident(payload, *, user_id=None):
    """Create a manual incident as AlertGroup + child Alert."""

    team_id = payload["team_id"]
    service_id = payload.get("service_id")
    title = payload["title"].strip()
    message = (payload.get("message") or "").strip()
    severity = payload.get("severity") or "critical"
    priority_slug = payload.get("priority")
    notify = payload.get("notify", True)

    team = _get_manual_incident_team(team_id)
    service = _get_manual_incident_service(service_id, team.id)

    manual_id = uuid4().hex
    group_key = f"manual:{manual_id}"
    now = utc_now()

    alert_data = {
        "source": "manual",
        "external_id": manual_id,
        "dedup_key": group_key,
        "title": title,
        "message": message,
        "severity": severity,
        "labels": {
            "alertname": title,
            "severity": severity,
            "source": "manual",
            "manual": "true",
            "manual_incident_id": manual_id,
            "team": team.slug,
            "team_id": str(team.id),
        },
        "payload": {
            "manual": True,
            "title": title,
            "message": message,
            "team_id": team.id,
            "service_id": service.id if service else None,
            "created_by_user_id": user_id,
        },
        "status": "firing",
    }

    if service:
        alert_data["labels"]["service"] = service.slug
        alert_data["labels"]["service_id"] = str(service.id)

    if user_id:
        alert_data["labels"]["created_by_user_id"] = str(user_id)

    priority = (
        incidents_repo.get_priority_by_slug(priority_slug)
        if priority_slug
        else incident_priority_from_alert(alert_data)
    )

    if priority_slug and not priority:
        raise ValueError("priority must be one of enabled incident priorities")

    priority_kwargs = incident_priority_create_kwargs(priority)

    rotation = get_effective_route_rotation(None, service)
    policy = get_effective_escalation_policy(None, service)

    policy_rule, rotation, assignee, next_escalation_at = (
        apply_initial_escalation_policy_assignment(policy, rotation)
    )

    with database_proxy.atomic():
        group = alerts_repo.create_alert_group(
            team=team.id,
            route=None,
            service=service.id if service else None,
            rotation=rotation.id if rotation else None,
            escalation_policy=policy.id if policy else None,
            escalation_rule=policy_rule.id if policy_rule else None,
            next_escalation_at=next_escalation_at,
            assignee=assignee.id if assignee else None,
            source="manual",
            group_key=group_key,
            title=title,
            message=message,
            severity=severity,
            status="firing",
            first_seen_at=now,
            last_seen_at=now,
            priority_set_manually=bool(priority_slug),
            priority_set_by=user_id if priority_slug else None,
            priority_set_at=now if priority_slug else None,
            **priority_kwargs,
        )

        alert = alerts_repo.create_alert(
            group=group.id,
            team=team.id,
            route=None,
            service=service.id if service else None,
            rotation=rotation.id if rotation else None,
            escalation_policy=policy.id if policy else None,
            escalation_rule=policy_rule.id if policy_rule else None,
            next_escalation_at=next_escalation_at,
            assignee=assignee.id if assignee else None,
            source="manual",
            external_id=manual_id,
            dedup_key=group_key,
            group_key=group_key,
            title=title,
            message=message,
            severity=severity,
            labels=alert_data["labels"],
            payload=alert_data["payload"],
            status="firing",
            first_seen_at=now,
            last_seen_at=now,
            **priority_kwargs,
        )

        alerts_repo.create_alert_event(
            alert_id=alert.id,
            group_id=group.id,
            event_type="manual_created",
            message="Manual incident created",
            user_id=user_id,
        )

        group = alerts_repo.recalculate_alert_group(group)

        _add_service_stakeholders_for_manual_incident(group)

        if notify:
            schedule_group_notification(
                group,
                reason="notification",
                now=now,
            )

    return group
