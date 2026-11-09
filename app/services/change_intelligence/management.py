"""Human administration of central and Group-owned Change integrations."""

from app.api.schemas.roles import GROUP_USER_ADMIN_ROLE
from app.modules.db.models import ChangeIntegration, Group, User, UserGroup
from app.services.change_intelligence.authorization import ChangeAccessDenied, lock_row
from app.services.admin_tokens import lock_admin_api_token
from app.services.rbac import current_api_token


def managed_groups(user):
    """Return active Groups administered by this user, regardless of UI filter."""
    groups = Group.select().where(Group.active == True, Group.deleted == False)
    token = current_api_token()
    if token and token.group_id is not None:
        groups = groups.where(Group.id == token.group_id)
    if user.is_admin:
        return groups
    memberships = UserGroup.select(UserGroup.group).where(
        UserGroup.user == user.id,
        UserGroup.role == GROUP_USER_ADMIN_ROLE,
        UserGroup.active == True,
    )
    return groups.where(Group.id.in_(memberships))


def can_manage_integrations(user):
    """Permit global administrators and active Group user administrators."""
    return bool(user and (user.is_admin or managed_groups(user).exists()))


def visible_integrations(user):
    """Central identities are never delegated through their sources or grants."""
    query = ChangeIntegration.select()
    if not can_manage_all_integrations(user):
        query = query.where(
            ChangeIntegration.owner_group.in_(managed_groups(user).select(Group.id))
        )
    return query


def can_manage_all_integrations(user):
    """Global operations cannot use a Group- or Team-restricted token."""
    token = current_api_token()
    return bool(
        user and user.is_admin
        and (token is None or (token.group_id is None and token.team_id is None))
    )


def require_manager(
    actor_id, group_id, *, creating=False, token_scope="change-integrations:write",
):
    """Lock user and token authority until commit, including concurrent revocation.

    Call after the catalog/integration locks. User and membership updates then
    either precede this check or wait for the authorized operation to commit.
    """
    user = lock_row(User.select().where(User.id == actor_id))
    if user is None or not user.active or user.deleted:
        raise ChangeAccessDenied("Change access denied")
    try:
        lock_admin_api_token(actor_id, token_scope, group_id=group_id)
    except PermissionError as error:
        raise ChangeAccessDenied("Change access denied") from error
    if user.is_admin and not creating:
        return
    if group_id is None:
        if user.is_admin:
            return
        raise ChangeAccessDenied("Change access denied")
    group = Group.get_or_none(
        Group.id == group_id, Group.active == True, Group.deleted == False
    )
    if group is None:
        raise ChangeAccessDenied("Change access denied")
    if user.is_admin:
        return
    membership = lock_row(
        UserGroup.select().where(UserGroup.user == user.id, UserGroup.group == group_id)
    )
    if (
        membership is None
        or not membership.active
        or membership.role != GROUP_USER_ADMIN_ROLE
    ):
        raise ChangeAccessDenied("Change access denied")
