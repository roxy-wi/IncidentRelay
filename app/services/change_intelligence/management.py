"""Human administration of central and Group-owned Change integrations."""

from app.api.schemas.roles import GROUP_USER_ADMIN_ROLE
from app.modules.db.models import ChangeIntegration, Group, User, UserGroup
from app.services.change_intelligence.authorization import ChangeAccessDenied, lock_row


def managed_groups(user):
    """Return active Groups administered by this user, regardless of UI filter."""
    groups = Group.select().where(Group.active == True, Group.deleted == False)
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
    if not user.is_admin:
        query = query.where(
            ChangeIntegration.owner_group.in_(managed_groups(user).select(Group.id))
        )
    return query


def require_manager(actor_id, group_id, *, creating=False):
    """Lock human authority until commit, including a concurrently revoked role.

    Call after the catalog/integration locks. User and membership updates then
    either precede this check or wait for the authorized operation to commit.
    """
    user = lock_row(User.select().where(User.id == actor_id))
    if user is None or not user.active or user.deleted:
        raise ChangeAccessDenied("Change access denied")
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
