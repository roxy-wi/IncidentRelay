from app.modules.common import utc_now
from app.modules.db import incidents_repo
from app.services.incidents.responders import (
    can_user_act_as_responder_target,
)
from app.services.serializers.alerts import serialize_incident_responder
from app.services.incidents.responder_display import user_display_name
from app.services.rbac import can_read_team, is_admin_user


def _responder_request_body(responder):
    requested_by = (
        responder.requested_by
        if responder.requested_by_id
        else None
    )
    requester = user_display_name(requested_by)

    if responder.message:
        return f"{requester}: {responder.message}"

    return f"{requester} requested your help with this incident."


def serialize_notification_center_responder_item(responder, current_user=None):
    incident = responder.incident
    url = f"/incidents/{incident.id}" if incident else None
    if incident and responder.target_type == "team" and not is_admin_user(current_user):
        if not incident.team_id or not can_read_team(current_user, incident.team_id):
            url = None

    return {
        "id": f"responder-request-{responder.id}",
        "type": "responder_request",
        "title": "Responder requested",
        "body": _responder_request_body(responder),
        "created_at": (
            responder.requested_at.isoformat()
            if responder.requested_at
            else None
        ),
        "expires_at": (
            responder.expires_at.isoformat()
            if responder.expires_at
            else None
        ),
        "url": url,
        "incident_id": incident.id if incident else None,
        "responder": serialize_incident_responder(responder),
        "actions": [
            {
                "id": "accept",
                "label": "Accept",
                "status": "accepted",
                "method": "PUT",
                "url": (
                    f"/api/incidents/{incident.id}/responders/{responder.id}"
                    if incident
                    else None
                ),
            },
            {
                "id": "decline",
                "label": "Decline",
                "status": "declined",
                "method": "PUT",
                "url": (
                    f"/api/incidents/{incident.id}/responders/{responder.id}"
                    if incident
                    else None
                ),
            },
        ],
    }


def list_notification_center_items(user, *, limit=20, responder_id=None):
    if not user:
        return {
            "items": [],
            "unread_count": 0,
        }

    if responder_id is None:
        candidates = incidents_repo.list_requested_incident_responders(limit=max(limit * 5, 50))
    else:
        row = incidents_repo.get_incident_responder(responder_id)
        candidates = [row] if row and row.status == "requested" else []

    items = []
    now = utc_now()
    for responder in candidates:
        if responder.expires_at and responder.expires_at <= now:
            continue
        if not can_user_act_as_responder_target(user, responder):
            continue

        items.append(
            serialize_notification_center_responder_item(
                responder,
                current_user=user,
            )
        )

        if len(items) >= limit:
            break

    return {
        "items": items,
        "unread_count": len(items),
    }
