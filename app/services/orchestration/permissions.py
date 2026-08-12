from typing import Dict, FrozenSet

from app.modules.db.models import UserGroup


VIEW = "orchestration.view"
CREATE = "orchestration.create"
EDIT = "orchestration.edit"
SIMULATE = "orchestration.simulate"
PUBLISH = "orchestration.publish"
DELETE = "orchestration.delete"
MANAGE_TOKENS = "orchestration.manage_tokens"
VIEW_EXECUTIONS = "orchestration.view_executions"
REPLAY = "orchestration.replay"
MANAGE_ACTIONS = "orchestration.manage_actions"

ALL_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        VIEW,
        CREATE,
        EDIT,
        SIMULATE,
        PUBLISH,
        DELETE,
        MANAGE_TOKENS,
        VIEW_EXECUTIONS,
        REPLAY,
        MANAGE_ACTIONS,
    }
)

GROUP_ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "viewer": frozenset({VIEW, VIEW_EXECUTIONS}),
    "editor": frozenset({VIEW, CREATE, EDIT, SIMULATE, VIEW_EXECUTIONS, REPLAY}),
    # user_admin is intentionally not treated as an orchestration publisher.
    "user_admin": frozenset({VIEW, VIEW_EXECUTIONS}),
}


def has_orchestration_permission(user, group_id: int, permission: str) -> bool:
    if permission not in ALL_PERMISSIONS:
        return False
    if bool(getattr(user, "is_admin", False)):
        return True

    membership = UserGroup.get_or_none(
        (UserGroup.user == user.id)
        & (UserGroup.group == group_id)
        & (UserGroup.active == True)  # noqa: E712
    )
    if membership is None:
        return False
    return permission in GROUP_ROLE_PERMISSIONS.get(membership.role, frozenset())
