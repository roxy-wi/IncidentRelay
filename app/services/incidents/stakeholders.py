"""Operational Incident stakeholders (independent of AlertGroup lifecycle)."""
import logging
from app.modules.db import incident_core_repo, incidents_repo

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


def notify_stakeholders(
    incident, event_type, old_value=None, skip_user_id=None, *, event_id=None,
):
    """Dispatch a queued event without re-enqueuing successful recipients."""
    from app.modules.db.models import IncidentEvent
    from app.services.notifications.incidents import dispatch_event

    event_names = {
        "created": "incident_declared",
        "priority_changed": "incident_updated",
        "status_changed": "incident_status_changed",
        "resolved": "incident_status_changed",
        "comment_added": "incident_comment_added",
    }
    if event_type not in event_names:
        raise ValueError("unsupported stakeholder notification event")
    try:
        if event_id is None:
            event = (IncidentEvent.select().where(
                IncidentEvent.incident == incident.id,
                IncidentEvent.event_type == event_names[event_type],
            ).order_by(IncidentEvent.id.desc()).first())
            if event is None:
                return 0
            event_id = event.id
        return dispatch_event(event_id)
    except Exception as exc:
        logger.error(
            "Stakeholder dispatch deferred: incident_id=%s error_type=%s",
            incident.id, type(exc).__name__,
        )
        return 0


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
