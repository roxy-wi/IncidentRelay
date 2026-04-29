from datetime import datetime

from app.models import AlertRoute, Group, NotificationChannel, Rotation, Silence, Team, UserGroup


def list_groups(active_only=False, include_deleted=False):
    """
    Return groups ordered by id.
    """

    query = Group.select().order_by(Group.id.asc())

    if not include_deleted:
        query = query.where(Group.deleted == False)

    if active_only:
        query = query.where(Group.active == True)

    return list(query)


def list_groups_for_user(user, write_required=False):
    """
    Return active groups visible to a user.
    """

    if user and user.is_admin:
        return list_groups(active_only=True)

    if not user:
        return []

    query = (
        UserGroup
        .select(UserGroup)
        .join(Group)
        .where(
            (UserGroup.user == user.id)
            & (UserGroup.active == True)
            & (Group.active == True)
            & (Group.deleted == False)
        )
        .order_by(UserGroup.id.asc())
    )

    if write_required:
        query = query.where(UserGroup.role == "rw")

    return [membership.group for membership in query]


def get_group(group_id, include_deleted=False):
    """
    Return a group by id.
    """

    query = Group.select().where(Group.id == group_id)

    if not include_deleted:
        query = query.where(Group.deleted == False)

    return query.get()


def create_group(slug, name, description=None):
    """
    Create a group.
    """

    return Group.create(slug=slug, name=name, description=description)


def update_group(group_id, data):
    """
    Update a group.
    """

    group = get_group(group_id)

    for field in ["slug", "name", "description", "active"]:
        if field in data:
            setattr(group, field, data[field])

    group.save()
    return group


def add_user_to_group(user_id, group_id, role="read_only"):
    """
    Add a user to a group.
    """

    membership, created = UserGroup.get_or_create(
        user=user_id,
        group=group_id,
        defaults={"role": role},
    )

    if not created:
        membership.role = role
        membership.active = True
        membership.save()

    return membership


def list_user_groups(user_id):
    """
    Return active group memberships for a user.
    """

    return list(
        UserGroup
        .select(UserGroup)
        .join(Group)
        .where(
            (UserGroup.user == user_id)
            & (Group.active == True)
            & (Group.deleted == False)
        )
        .order_by(UserGroup.id.asc())
    )


def get_user_group_role(user_id, group_id):
    """
    Return the role a user has in an active group.
    """

    membership = (
        UserGroup
        .select(UserGroup)
        .join(Group)
        .where(
            (UserGroup.user == user_id)
            & (UserGroup.group == group_id)
            & (UserGroup.active == True)
            & (Group.active == True)
            & (Group.deleted == False)
        )
        .first()
    )

    return membership.role if membership else None


def get_group_membership(membership_id):
    """
    Return a group membership by id.
    """

    return UserGroup.get_by_id(membership_id)


def update_group_membership(membership_id, role, active=True):
    """
    Update a group membership.
    """

    membership = get_group_membership(membership_id)
    membership.role = role
    membership.active = active
    membership.save()
    return membership


def disable_group_membership(membership_id):
    """
    Disable a group membership.
    """

    membership = get_group_membership(membership_id)
    membership.active = False
    membership.save()
    return membership


def soft_delete_group(group_id):
    """
    Soft-delete a group and disable all resources under it.
    """

    now = datetime.utcnow()

    group = get_group(group_id)
    group.deleted = True
    group.deleted_at = now
    group.active = False
    group.save()

    teams = Team.select().where(
        (Team.group == group_id)
        & (Team.deleted == False)
    )

    for team in teams:
        team.deleted = True
        team.deleted_at = now
        team.active = False
        team.save()

        Rotation.update(
            deleted=True,
            deleted_at=now,
            enabled=False,
        ).where(
            (Rotation.team == team.id)
            & (Rotation.deleted == False)
        ).execute()

        AlertRoute.update(
            deleted=True,
            deleted_at=now,
            enabled=False,
        ).where(
            (AlertRoute.team == team.id)
            & (AlertRoute.deleted == False)
        ).execute()

        NotificationChannel.update(
            deleted=True,
            deleted_at=now,
            enabled=False,
        ).where(
            (NotificationChannel.team == team.id)
            & (NotificationChannel.deleted == False)
        ).execute()

        Silence.update(
            deleted=True,
            deleted_at=now,
            enabled=False,
        ).where(
            (Silence.team == team.id)
            & (Silence.deleted == False)
        ).execute()

    return group
