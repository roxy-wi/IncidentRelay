from app.modules.db import incidents_repo
from app.services.incidents.responders import (
    can_user_act_as_responder_target,
)
from app.services.links import build_alert_web_url
from app.services.serializers import (
    serialize_incident,
    serialize_incident_responder,
)
from app.services.incidents.responder_display import user_display_name


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
    group = responder.group

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
        "url": build_alert_web_url(group),
        "incident_id": group.id if group else None,
        "incident": serialize_incident(
            group,
            current_user=current_user,
            include_details=False,
        ) if group else None,
        "responder": serialize_incident_responder(responder),
        "actions": [
            {
                "id": "accept",
                "label": "Accept",
                "status": "accepted",
                "method": "PUT",
                "url": (
                    f"/api/incidents/{group.id}/responders/{responder.id}"
                    if group
                    else None
                ),
            },
            {
                "id": "decline",
                "label": "Decline",
                "status": "declined",
                "method": "PUT",
                "url": (
                    f"/api/incidents/{group.id}/responders/{responder.id}"
                    if group
                    else None
                ),
            },
        ],
    }


def list_notification_center_items(user, *, limit=20):
    if not user:
        return {
            "items": [],
            "unread_count": 0,
        }

    candidates = incidents_repo.list_requested_incident_responders(
        limit=max(limit * 5, 50),
    )

    items = []

    for responder in candidates:
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
