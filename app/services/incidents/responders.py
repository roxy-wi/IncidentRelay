import logging

from peewee import IntegrityError

from app import Config
from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import incident_core_repo, incidents_repo
from app.modules.db.models import (
    EscalationPolicy,
    Rotation,
    RotationLayer,
    RotationLayerMember,
    RotationMember,
    Team,
    User,
    UserGroup,
)
from app.services.incidents.core import _audit
from app.services.incidents.responder_display import (
    responder_target_label,
    user_display_name,
)
from app.services.incidents.responder_notifications import (
    notify_incident_responder_requested,
)
from app.services.rbac import can_respond_team, can_write_group
from app.services.notifications.incidents import enqueue_responder

logger = logging.getLogger("oncall.incidents.responders")

VALID_RESPONDER_UPDATE_STATUSES = {
    "accepted",
    "declined",
    "expired",
    "resolved",
}

RESPONDER_STATUS_TRANSITIONS = {
    "requested": {"accepted", "declined", "expired"},
    "accepted": {"resolved"},
    "declined": set(),
    "expired": set(),
    "resolved": set(),
}
RESPONDER_TARGET_ACTION_STATUSES = {"accepted", "declined"}
RESPONDER_TARGET_FIELDS = {
    "user": "target_user_id",
    "team": "target_team_id",
    "rotation": "target_rotation_id",
    "escalation_policy": "target_escalation_policy_id",
}


def _incident_group_id(group):
    if getattr(group, "team_id", None) and group.team:
        return group.team.group_id
    return None


def _is_user_in_group(user_id, group_id):
    if not group_id:
        return True

    return (
        UserGroup
        .select()
        .where(
            UserGroup.user == user_id,
            UserGroup.group == group_id,
            UserGroup.active == True,
        )
        .exists()
    )


def _validate_responder_user(target_id, group):
    user = User.get_or_none(
        User.id == target_id,
        User.active == True,
        User.deleted == False,
    )
    if not user:
        raise ValueError("target_user_id points to missing or inactive user")

    group_id = _incident_group_id(group)
    if group_id and not _is_user_in_group(user.id, group_id):
        raise ValueError("target user is not a member of incident group")

    return user


def _validate_responder_team(target_id, group):
    team = Team.get_or_none(
        Team.id == target_id,
        Team.active == True,
        Team.deleted == False,
    )
    if not team:
        raise ValueError("target_team_id points to missing or inactive team")

    group_id = _incident_group_id(group)
    if group_id and team.group_id != group_id:
        raise ValueError("target team belongs to another group")

    return team


def _validate_responder_rotation(target_id, group):
    rotation = Rotation.get_or_none(
        Rotation.id == target_id,
        Rotation.enabled == True,
        Rotation.deleted == False,
    )
    if not rotation:
        raise ValueError("target_rotation_id points to missing or disabled rotation")

    team = rotation.team
    if not team or team.deleted or not team.active:
        raise ValueError("target rotation belongs to missing or inactive team")

    group_id = _incident_group_id(group)
    if group_id and team.group_id != group_id:
        raise ValueError("target rotation belongs to another group")

    return rotation


def _validate_responder_escalation_policy(target_id, group):
    policy = EscalationPolicy.get_or_none(
        EscalationPolicy.id == target_id,
        EscalationPolicy.enabled == True,
        EscalationPolicy.deleted == False,
    )
    if not policy:
        raise ValueError(
            "target_escalation_policy_id points to missing or disabled "
            "escalation policy"
        )

    team = policy.team
    if not team or team.deleted or not team.active:
        raise ValueError(
            "target escalation policy belongs to missing or inactive team"
        )

    group_id = _incident_group_id(group)
    if group_id and team.group_id != group_id:
        raise ValueError("target escalation policy belongs to another group")

    return policy


def _validate_responder_target(group, target_type, target_id):
    validators = {
        "user": _validate_responder_user,
        "team": _validate_responder_team,
        "rotation": _validate_responder_rotation,
        "escalation_policy": _validate_responder_escalation_policy,
    }

    validators[target_type](target_id, group)

    existing = incidents_repo.find_open_incident_responder(
        group.id,
        target_type,
        target_id,
    )
    if existing:
        raise incident_core_repo.IncidentConflictError(
            "active responder request already exists for this target"
        )


def _validate_responder_status_transition(current_status, next_status):
    if current_status == next_status:
        return

    allowed = RESPONDER_STATUS_TRANSITIONS.get(current_status, set())
    if next_status not in allowed:
        raise incident_core_repo.IncidentConflictError(
            f"cannot change responder status from {current_status} to {next_status}"
        )


def _can_operate_incident_responders(user, group):
    """Return True when user can manage responder requests for the incident."""
    if not user:
        return False

    if user.is_admin:
        return True

    if group.team_id:
        return can_respond_team(user, group.team_id)

    group_id = _incident_group_id(group)
    if group_id:
        return can_write_group(user, group_id)

    return False


def _is_active_rotation_member(user_id, rotation_id):
    """Return True when user belongs to the responder rotation."""
    if not user_id or not rotation_id:
        return False

    legacy_member_exists = (
        RotationMember
        .select()
        .where(
            RotationMember.rotation == rotation_id,
            RotationMember.user == user_id,
            RotationMember.active == True,
        )
        .exists()
    )
    if legacy_member_exists:
        return True

    active_layer_ids = (
        RotationLayer
        .select(RotationLayer.id)
        .where(
            RotationLayer.rotation == rotation_id,
            RotationLayer.enabled == True,
            RotationLayer.deleted == False,
        )
    )

    return (
        RotationLayerMember
        .select()
        .where(
            RotationLayerMember.layer.in_(active_layer_ids),
            RotationLayerMember.user == user_id,
            RotationLayerMember.active == True,
            RotationLayerMember.ends_at.is_null(True),
        )
        .exists()
    )


def _can_act_as_responder_target(user, responder, status):
    """Return True when user can accept/decline this responder request."""
    if not user:
        return False

    if status not in RESPONDER_TARGET_ACTION_STATUSES:
        return False

    if responder.target_type == "user":
        return responder.target_user_id == user.id

    if responder.target_type == "team":
        if not responder.target_team_id:
            return False
        return can_respond_team(user, responder.target_team_id)

    if responder.target_type == "rotation":
        return _is_active_rotation_member(
            user.id,
            responder.target_rotation_id,
        )

    if responder.target_type == "escalation_policy":
        if not responder.target_escalation_policy_id:
            return False

        policy = EscalationPolicy.get_or_none(
            EscalationPolicy.id == responder.target_escalation_policy_id,
            EscalationPolicy.deleted == False,
        )
        if not policy or not policy.team_id:
            return False

        return can_respond_team(user, policy.team_id)

    return False


def can_user_act_as_responder_target(user, responder):
    """Return True when user can accept or decline this responder request."""
    return _can_act_as_responder_target(
        user,
        responder,
        "accepted",
    )


def responder_status_event_message(
    responder,
    status,
    *,
    response_message=None,
    user=None,
):
    target_label = responder_target_label(responder)
    actor = user_display_name(user)

    if status == "accepted":
        base = f"{actor} accepted responder request for {target_label}"
    elif status == "declined":
        base = f"{actor} declined responder request for {target_label}"
    elif status == "resolved":
        base = f"{actor} resolved responder request for {target_label}"
    elif status == "expired":
        base = f"Responder request expired for {target_label}"
    else:
        base = f"{actor} changed responder request for {target_label} to {status}"

    if response_message:
        return f"{base}. {response_message}"

    return base


def require_incident_responder_action_allowed(user, group, responder, status):
    """Raise PermissionError if user cannot update responder status."""
    if _can_operate_incident_responders(user, group):
        return

    if _can_act_as_responder_target(user, responder, status):
        return

    raise PermissionError(
        "Only incident responders or the requested responder target "
        "can update this responder request"
    )


def create_incident_responder(
    *, incident_id, payload, user_id=None, api_token_id=None, source="system",
):
    """Create the request, event and audit record before sending notifications."""
    target_type = payload["target_type"]
    required_field = RESPONDER_TARGET_FIELDS[target_type]
    target_id = payload[required_field]
    expires_after_minutes = payload.get("expires_after_minutes")
    if expires_after_minutes is None:
        expires_after_minutes = int(
            getattr(Config, "INCIDENT_RESPONDER_DEFAULT_EXPIRES_AFTER_MINUTES", 30)
        )
    with incident_core_repo.incident_transaction(incident_id) as incident:
        _validate_responder_target(incident, target_type, target_id)
        responder = incidents_repo.create_incident_responder(
            incident.id,
            {
                "target_type": target_type,
                required_field: target_id,
                "role": "responder",
                "requested_by_id": user_id,
                "message": payload.get("message"),
                "expires_after_minutes": expires_after_minutes,
                "status": "requested",
            },
        )
        message = f"Responder requested: {responder_target_label(responder)}"
        if payload.get("message"):
            message += f". {payload['message']}"
        event = incident_core_repo.create_event(
            incident.id, "responder_requested", message=message, user_id=user_id,
            data={"responder_id": responder.id},
        )
        _audit(
            "incident.responder.request", incident, user_id=user_id,
            api_token_id=api_token_id, source=source,
            data={"responder_id": responder.id},
        )
        enqueue_responder(responder, event)
    notify_incident_responder_requested(responder)
    return incidents_repo.get_incident_responder(responder.id)


def set_incident_responder_status(
    *, incident_id, responder_id, status, response_message=None, user_id=None,
    user=None, api_token_id=None, source="system",
):
    """Change a request and its assignment, event and audit atomically."""
    if status not in VALID_RESPONDER_UPDATE_STATUSES:
        raise ValueError("status must be one of: accepted, declined, expired, resolved")
    if user_id is None and user:
        user_id = user.id
    with incident_core_repo.incident_transaction(incident_id) as incident:
        responder = incidents_repo.get_incident_responder(responder_id)
        if not responder or responder.incident_id != incident.id:
            raise LookupError("responder not found in this incident")
        require_incident_responder_action_allowed(user, incident, responder, status)
        if responder.status == status:
            # Repeated requests must not replace the original actor, response or
            # concrete assignee, nor produce duplicate events and audit entries.
            if (
                status == "accepted"
                and responder.target_type != "user"
                and responder.target_user_id != user_id
            ):
                raise incident_core_repo.IncidentConflictError(
                    "responder request was accepted by another user"
                )
            return responder
        _validate_responder_status_transition(responder.status, status)
        if (
            status in {"accepted", "declined"}
            and responder.expires_at
            and responder.expires_at <= utc_now()
        ):
            raise incident_core_repo.IncidentConflictError("responder request has expired")

        assignee_id = None
        if status == "accepted":
            assignee_id = (
                responder.target_user_id if responder.target_type == "user"
                else user_id
            )
            _validate_responder_user(assignee_id, incident)
            if incidents_repo.has_participant_conflict(
                incident.id, assignee_id, responder.role, exclude_id=responder.id,
            ):
                raise incident_core_repo.IncidentConflictError("participant already assigned")
        try:
            # A savepoint keeps PostgreSQL usable if a uniqueness constraint
            # rejects a competing assignment made outside this service.
            with db.atomic():
                updated = incidents_repo.update_incident_responder_status(
                    responder.id, status, expected_status=responder.status,
                    user_id=user_id, response_message=response_message,
                    target_user_id=assignee_id,
                )
        except IntegrityError as exc:
            if status == "accepted" and incidents_repo.has_participant_conflict(
                incident.id, assignee_id, responder.role, exclude_id=responder.id,
            ):
                raise incident_core_repo.IncidentConflictError(
                    "participant already assigned"
                ) from exc
            raise
        incident_core_repo.create_event(
            incident.id, f"responder_{status}", user_id=user_id,
            message=responder_status_event_message(
                updated, status, response_message=response_message, user=user,
            ),
            data={"responder_id": updated.id, "user_id": updated.target_user_id},
        )
        _audit(
            "incident.responder.status", incident, user_id=user_id,
            api_token_id=api_token_id, source=source,
            data={"responder_id": updated.id, "status": updated.status},
        )
    return updated


def expire_due_incident_responders(*, limit=100):
    """Expire each request together with its event and audit record."""
    expired = 0
    skipped = 0
    responders = incidents_repo.list_expired_requested_responders(limit=limit)
    for responder in responders:
        with incident_core_repo.incident_transaction(responder.incident_id) as incident:
            expired_responder = incidents_repo.expire_incident_responder(responder.id)
            if not expired_responder:
                skipped += 1
                continue
            incident_core_repo.create_event(
                incident.id, "responder_expired", user_id=None,
                message=responder_status_event_message(expired_responder, "expired"),
                data={"responder_id": expired_responder.id},
            )
            _audit(
                "incident.responder.status", incident, source="system",
                data={"responder_id": expired_responder.id, "status": "expired"},
            )
        expired += 1
    return {"processed": expired + skipped, "expired": expired, "skipped": skipped}
