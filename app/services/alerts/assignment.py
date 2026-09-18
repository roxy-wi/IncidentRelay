"""Manual AlertGroup technical-assignee management.

AlertGroup assignment represents technical responsibility / paging ownership.
It is intentionally independent from first-class Incident operational ownership
and must never acknowledge a group or reset escalation state.
"""

from __future__ import annotations

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import alerts_repo, audit_repo
from app.modules.db.models import AlertGroup, Team, TeamUser, User


class AlertGroupAssignmentError(ValueError):
    """Raised when a requested AlertGroup assignee is invalid."""


def _resolve_group(group_or_id) -> AlertGroup:
    if isinstance(group_or_id, AlertGroup):
        return group_or_id

    try:
        group_id = int(group_or_id)
    except (TypeError, ValueError) as exc:
        raise AlertGroupAssignmentError("alert group not found") from exc

    group = AlertGroup.get_or_none(AlertGroup.id == group_id)
    if not group:
        raise AlertGroupAssignmentError("alert group not found")
    return group


def _resolve_assignee(assignee_id, team_id: int | None) -> User | None:
    if assignee_id in (None, ""):
        return None

    if not team_id:
        raise AlertGroupAssignmentError(
            "cannot assign a user to an AlertGroup without a team"
        )

    try:
        user_id = int(assignee_id)
    except (TypeError, ValueError) as exc:
        raise AlertGroupAssignmentError("assignee_id must be an integer") from exc

    user = User.get_or_none(
        User.id == user_id,
        User.active == True,  # noqa: E712
        User.deleted == False,  # noqa: E712
    )
    if not user:
        raise AlertGroupAssignmentError(
            "assignee_id points to a missing or inactive user"
        )

    membership_exists = (
        TeamUser.select()
        .where(
            TeamUser.team == team_id,
            TeamUser.user == user.id,
            TeamUser.active == True,  # noqa: E712
        )
        .exists()
    )
    if not membership_exists:
        raise AlertGroupAssignmentError(
            "assignee must be an active member of the AlertGroup team"
        )

    return user


def set_alert_group_assignee(
    group_or_id,
    assignee_id,
    *,
    actor_user_id=None,
) -> AlertGroup:
    """Change only the technical assignee of one AlertGroup.

    This operation deliberately leaves acknowledgement and all escalation
    fields untouched. Incident operational assignment is a separate domain.
    """

    group = _resolve_group(group_or_id)
    assignee = _resolve_assignee(assignee_id, group.team_id)
    old_assignee_id = group.assignee_id
    new_assignee_id = getattr(assignee, "id", None)

    if old_assignee_id == new_assignee_id:
        return group

    team = Team.get_or_none(Team.id == group.team_id) if group.team_id else None
    now = utc_now()

    with db.atomic():
        updated = (
            AlertGroup.update(
                assignee=new_assignee_id,
                updated_at=now,
            )
            .where(AlertGroup.id == group.id)
            .execute()
        )
        if updated != 1:
            raise AlertGroupAssignmentError("alert group no longer exists")

        event_message = (
            f"Technical assignee changed from {old_assignee_id or '-'} "
            f"to {new_assignee_id or '-'}"
        )
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="assignee_changed",
            message=event_message,
            user_id=actor_user_id,
        )

        audit_repo.create_audit_log(
            action="alert_group_assignee_changed",
            object_type="alert_group",
            object_id=group.id,
            group_id=getattr(team, "group_id", None),
            team_id=group.team_id,
            user_id=actor_user_id,
            data={
                "from_user_id": old_assignee_id,
                "to_user_id": new_assignee_id,
            },
        )

    return AlertGroup.get_by_id(group.id)
