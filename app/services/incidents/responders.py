import logging

from app import Config
from app.modules.db import incidents_repo, alerts_repo
from app.modules.db.models import User, UserGroup, Team, Rotation, EscalationPolicy, RotationMember, \
    RotationLayer, RotationLayerMember
from app.services.rbac import can_respond_team, can_write_group
from app.services.incidents.responder_notifications import notify_incident_responder_requested
from app.services.incidents.responder_display import (
    responder_target_label,
    user_display_name,
)

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
        raise ValueError("active responder request already exists for this target")


def _validate_responder_status_transition(current_status, next_status):
    if current_status == next_status:
        return

    allowed = RESPONDER_STATUS_TRANSITIONS.get(current_status, set())
    if next_status not in allowed:
        raise ValueError(
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


def create_incident_responder(*, group_id, payload, user_id=None):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    target_type = payload["target_type"]
    required_field = RESPONDER_TARGET_FIELDS[target_type]
    target_id = payload[required_field]

    _validate_responder_target(
        group,
        target_type,
        target_id,
    )

    expires_after_minutes = payload.get("expires_after_minutes")
    if expires_after_minutes is None:
        expires_after_minutes = int(
            getattr(
                Config,
                "INCIDENT_RESPONDER_DEFAULT_EXPIRES_AFTER_MINUTES",
                30,
            )
        )

    target_data = {
        "target_user_id": None,
        "target_team_id": None,
        "target_rotation_id": None,
        "target_escalation_policy_id": None,
    }
    target_data[required_field] = target_id

    responder = incidents_repo.create_incident_responder(
        group.id,
        {
            "target_type": target_type,
            **target_data,
            "requested_by_id": user_id,
            "message": payload.get("message"),
            "expires_after_minutes": expires_after_minutes,
            "status": "requested",
        },
    )

    target_label = responder_target_label(responder)
    request_message = payload.get("message")

    if request_message:
        event_message = f"Responder requested: {target_label}. {request_message}"
    else:
        event_message = f"Responder requested: {target_label}"

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="responder_requested",
        message=event_message,
        user_id=user_id,
    )

    notify_incident_responder_requested(responder)

    responder = incidents_repo.get_incident_responder(responder.id)

    return responder


def set_incident_responder_status(
    *,
    group_id,
    responder_id,
    status,
    response_message=None,
    user_id=None,
    user=None,
):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    if status not in VALID_RESPONDER_UPDATE_STATUSES:
        raise ValueError(
            "status must be one of: accepted, declined, expired, resolved"
        )

    responder = incidents_repo.get_incident_responder(responder_id)

    if not responder or responder.group_id != group.id:
        raise LookupError("responder not found in this incident")

    require_incident_responder_action_allowed(
        user,
        group,
        responder,
        status,
    )

    _validate_responder_status_transition(responder.status, status)

    if user_id is None and user:
        user_id = user.id

    responder = incidents_repo.update_incident_responder_status(
        responder.id,
        status,
        user_id=user_id,
        response_message=response_message,
    )

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type=f"responder_{status}",
        message=responder_status_event_message(
            responder,
            status,
            response_message=response_message,
            user=user,
        ),
        user_id=user_id,
    )

    return responder


def expire_due_incident_responders(*, limit=100):
    """Expire responder requests that were not accepted or declined in time."""
    expired = 0
    skipped = 0

    responders = incidents_repo.list_expired_requested_responders(
        limit=limit,
    )

    for responder in responders:
        expired_responder = incidents_repo.expire_incident_responder(
            responder.id,
        )

        if not expired_responder:
            skipped += 1
            continue

        expired += 1

        alerts_repo.create_alert_event(
            group_id=expired_responder.group_id,
            event_type="responder_expired",
            message=responder_status_event_message(
                expired_responder,
                "expired",
            ),
            user_id=None,
        )

    return {
        "processed": expired + skipped,
        "expired": expired,
        "skipped": skipped,
    }
