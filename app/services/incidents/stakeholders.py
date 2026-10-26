"""Operational Incident stakeholders (independent of AlertGroup lifecycle)."""
import logging
from app.modules.db import incident_core_repo, incidents_repo
from app.modules.db.models import User, ServiceOwner, IncidentStakeholder
from app.notifiers.browser_push import service as browser_push

logger = logging.getLogger("oncall.incidents.stakeholders")

VALID_STAKEHOLDER_ROLES = {"stakeholder", "communications", "observer",
                           "business_owner", "executive", "support", "customer_success", "custom"}


def stakeholder_user(stakeholder):
    return stakeholder.user if stakeholder.user_id else None


def stakeholder_email(stakeholder):
    if stakeholder.email:
        return stakeholder.email
    user = stakeholder_user(stakeholder)
    return user.email if user else None


def send_stakeholder_email(recipient, subject, body):
    # Delegate to the installed mail delivery function used by the application.
    from app.services.incidents.stakeholder_mail import send_incident_mail
    return send_incident_mail(recipient, subject, body)


def notify_stakeholders(incident, event_type, old_value=None, skip_user_id=None):
    """Deliver Incident-only notification; per-stakeholder flags are respected."""
    flag = {"created": "notify_on_created", "priority_changed": "notify_on_priority_change",
            "status_changed": "notify_on_status_change", "resolved": "notify_on_resolved",
            "comment_added": "notify_on_comment"}.get(event_type)
    if not flag:
        raise ValueError("unsupported stakeholder notification event")
    sent = 0
    subject = f"Incident #{incident.id}: {incident.title} ({event_type})"
    body = f"Incident: {incident.title}\nStatus: {incident.workflow_status}\nURL: /incidents/{incident.id}"
    for stakeholder in incidents_repo.list_incident_stakeholders(incident.id):
        if skip_user_id and stakeholder.user_id == skip_user_id:
            continue
        if not getattr(stakeholder, flag, False):
            continue
        try:
            recipient = stakeholder_email(stakeholder)
            if recipient:
                send_stakeholder_email(recipient, subject, body)
                sent += 1
            if stakeholder.user_id:
                sent += browser_push.send_incident_push_to_user(
                    stakeholder.user, incident, event_type=event_type,
                    context={"message": body})
        except Exception:
            logger.exception("Incident stakeholder delivery failed: incident_id=%s stakeholder_id=%s",
                             incident.id, stakeholder.id)
            incident_core_repo.create_event(incident.id, "stakeholder_notification_failed",
                                            data={"stakeholder_id": stakeholder.id, "event_type": event_type})
    return sent


def create_incident_stakeholder(*, incident_id, payload, user_id=None):
    incident = incident_core_repo.get_incident(incident_id)
    if incident is None:
        raise LookupError("Incident not found")
    role = payload.get("role") or "stakeholder"
    if role not in VALID_STAKEHOLDER_ROLES:
        raise ValueError("invalid stakeholder role")
    if not payload.get("user_id") and not payload.get("email"):
        raise ValueError("user_id or email required")
    stakeholder = incidents_repo.create_incident_stakeholder(incident.id, {
        **payload, "role": role, "source": "manual", "created_by_id": user_id})
    incident_core_repo.create_event(incident.id, "stakeholder_added", user_id=user_id,
                                    data={"stakeholder_id": stakeholder.id})
    return stakeholder


def remove_incident_stakeholder(*, incident_id, stakeholder_id, user_id=None):
    stakeholder = incidents_repo.get_incident_stakeholder(stakeholder_id)
    if not stakeholder or stakeholder.incident_id != incident_id or not stakeholder.active:
        raise LookupError("Stakeholder not found")
    incidents_repo.deactivate_incident_stakeholder(stakeholder.id)
    incident_core_repo.create_event(incident_id, "stakeholder_removed", user_id=user_id,
                                    data={"stakeholder_id": stakeholder.id})
    return stakeholder
