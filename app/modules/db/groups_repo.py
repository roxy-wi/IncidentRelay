from datetime import datetime

from app.db import database_proxy as db
from app.api.schemas.roles import (
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
    GROUP_VIEWER_ROLE,
)
from app.modules.db.models import (
    AlertRoute,
    ApiToken,
    Group,
    NotificationChannel,
    Rotation,
    RotationLayer,
    RotationLayerMember,
    RotationLayerRestriction,
    RotationMember,
    RotationOverride,
    Silence,
    Team,
    TeamUser,
    User,
    UserGroup,
)
from app.modules.common import utc_now


def list_groups(active_only=False, include_deleted=False):
    """Return groups ordered by id."""
    query = Group.select().order_by(Group.id.asc())
    if not include_deleted:
        query = query.where(Group.deleted == False)
    if active_only:
        query = query.where(Group.active == True)
    return list(query)


def list_groups_for_user(user, write_required=False, manage_users_required=False):
    """Return active groups visible to a user."""
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

    if manage_users_required:
        query = query.where(UserGroup.role == GROUP_USER_ADMIN_ROLE)
    elif write_required:
        query = query.where(
            UserGroup.role.in_([
                GROUP_EDITOR_ROLE,
                GROUP_USER_ADMIN_ROLE,
            ])
        )

    return [membership.group for membership in query]


def get_group(group_id, include_deleted=False):
    """Return a group by id."""
    query = Group.select().where(Group.id == group_id)
    if not include_deleted:
        query = query.where(Group.deleted == False)
    return query.get()


def create_group(slug, name, description=None, active=True):
    """Create a group."""
    return Group.create(
        slug=slug,
        name=name,
        description=description,
        active=active,
    )


def update_group(group_id, data):
    """Update a group."""
    group = get_group(group_id)
    for field in ["slug", "name", "description", "active"]:
        if field in data:
            setattr(group, field, data[field])
    group.save()
    return group


def add_user_to_group(user_id, group_id, role=GROUP_VIEWER_ROLE, active=True):
    """Add a user to a group."""
    membership, created = UserGroup.get_or_create(
        user=user_id,
        group=group_id,
        defaults={
            "role": role,
            "active": active,
        },
    )

    if not created:
        membership.role = role
        membership.active = active
        membership.save()

    return membership


def list_user_groups(user_id):
    """Return active group memberships for a user."""
    return list(
        UserGroup
        .select(UserGroup)
        .join(Group)
        .where(
            (UserGroup.user == user_id)
            & (UserGroup.active == True)
            & (Group.active == True)
            & (Group.deleted == False)
        )
        .order_by(UserGroup.id.asc())
    )


def get_user_group_role(user_id, group_id):
    """Return the role a user has in an active group."""
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
    """Return a group membership by id."""
    return UserGroup.get_by_id(membership_id)


def update_group_membership(membership_id, role, active=True):
    """Update a group membership."""
    membership = get_group_membership(membership_id)
    membership.role = role
    membership.active = active
    membership.save()
    return membership


def soft_delete_group(group_id):
    """Soft-delete a group and disable all resources under it.

    The operation is intentionally soft-delete based:
    - historical alerts and audit logs stay readable;
    - teams/routes/rotations/channels/silences are disabled;
    - users are not deleted;
    - group memberships are disabled.
    """
    now = utc_now()
    with db.atomic():
        group = get_group(group_id)
        group.deleted = True
        group.deleted_at = now
        group.active = False
        group.save()

        team_ids = [
            team.id for team in (
                Team
                .select(Team.id)
                .where(
                    (Team.group == group_id)
                    & (Team.deleted == False)
                )
            )
        ]

        Team.update(
            deleted=True,
            deleted_at=now,
            active=False,
        ).where(
            (Team.group == group_id)
            & (Team.deleted == False)
        ).execute()

        UserGroup.update(
            active=False,
        ).where(
            UserGroup.group == group_id
        ).execute()

        User.update(
            active_group=None,
        ).where(
            User.active_group == group_id
        ).execute()

        if team_ids:
            rotation_ids = [
                rotation.id
                for rotation in (
                    Rotation
                    .select(Rotation.id)
                    .where(Rotation.team.in_(team_ids))
                )
            ]

            layer_ids = [
                layer.id
                for layer in (
                    RotationLayer
                    .select(RotationLayer.id)
                    .where(RotationLayer.rotation.in_(rotation_ids))
                )
            ]

            if layer_ids:
                RotationLayerRestriction.delete().where(
                    RotationLayerRestriction.layer.in_(layer_ids)
                ).execute()

                RotationLayerMember.delete().where(
                    RotationLayerMember.layer.in_(layer_ids)
                ).execute()

                RotationLayer.update(
                    deleted=True,
                    deleted_at=now,
                    enabled=False,
                ).where(
                    RotationLayer.id.in_(layer_ids)
                ).execute()
            Rotation.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
            ).where(
                (Rotation.team.in_(team_ids))
                & (Rotation.deleted == False)
            ).execute()

            AlertRoute.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
            ).where(
                (AlertRoute.team.in_(team_ids))
                & (AlertRoute.deleted == False)
            ).execute()

            NotificationChannel.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
            ).where(
                (NotificationChannel.team.in_(team_ids))
                & (NotificationChannel.deleted == False)
            ).execute()

            Silence.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
            ).where(
                (Silence.team.in_(team_ids))
                & (Silence.deleted == False)
            ).execute()

            TeamUser.update(
                active=False,
            ).where(
                TeamUser.team.in_(team_ids)
            ).execute()

            ApiToken.update(
                deleted=True,
                deleted_at=now,
                active=False,
            ).where(
                (
                    (ApiToken.team.in_(team_ids))
                    | (ApiToken.group == group_id)
                )
                & (ApiToken.deleted == False)
            ).execute()
        else:
            ApiToken.update(
                deleted=True,
                deleted_at=now,
                active=False,
            ).where(
                (ApiToken.group == group_id)
                & (ApiToken.deleted == False)
            ).execute()

        NotificationChannel.update(
            deleted=True,
            deleted_at=now,
            enabled=False,
        ).where(
            (NotificationChannel.group == group_id)
            & (NotificationChannel.deleted == False)
        ).execute()

    return group


def delete_group_membership(membership_id: int) -> dict:
    """Permanently remove user from group, all group teams and all group rotations."""
    membership = get_group_membership(membership_id)
    group_id = membership.group.id
    user_id = membership.user.id

    with db.atomic():
        team_ids_query = (
            Team
            .select(Team.id)
            .where(Team.group == group_id)
        )
        rotation_ids_query = (
            Rotation
            .select(Rotation.id)
            .where(Rotation.team.in_(team_ids_query))
        )

        layer_ids_query = (
            RotationLayer
            .select(RotationLayer.id)
            .where(RotationLayer.rotation.in_(rotation_ids_query))
        )

        removed_rotation_members = (
            RotationMember
            .delete()
            .where(
                (RotationMember.user == user_id)
                & (RotationMember.rotation.in_(rotation_ids_query))
            )
            .execute()
        )

        removed_layer_members = (
            RotationLayerMember
            .delete()
            .where(
                (RotationLayerMember.user == user_id)
                & (RotationLayerMember.layer.in_(layer_ids_query))
            )
            .execute()
        )

        removed_overrides = (
            RotationOverride
            .delete()
            .where(
                (RotationOverride.user == user_id)
                & (RotationOverride.rotation.in_(rotation_ids_query))
            )
            .execute()
        )

        removed_team_memberships = (
            TeamUser
            .delete()
            .where(
                (TeamUser.user == user_id)
                & (TeamUser.team.in_(team_ids_query))
            )
            .execute()
        )

        membership.delete_instance()

    return {
        "id": membership_id,
        "group_id": group_id,
        "user_id": user_id,
        "removed_rotation_members": removed_rotation_members,
        "removed_rotation_layer_members": removed_layer_members,
        "removed_rotation_overrides": removed_overrides,
        "removed_team_memberships": removed_team_memberships,
    }
