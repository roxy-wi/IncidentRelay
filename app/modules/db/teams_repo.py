from peewee import JOIN

from app.api.schemas.roles import TEAM_VIEWER_ROLE
from app.db import database_proxy
from app.modules.db.models import (
    Group,
    Rotation,
    RotationMember,
    RotationOverride,
    RotationLayer,
    RotationLayerMember,
    Team,
    TeamUser,
)


def list_teams(active_only=False, group_ids=None, include_deleted=False):
    """Return teams ordered by id."""
    query = Team.select().order_by(Team.id.asc())
    if not include_deleted:
        query = query.where(Team.deleted == False)
    if group_ids is not None:
        if not group_ids:
            return []
        query = query.where(Team.group.in_(group_ids))
    if active_only:
        query = query.where(Team.active == True)
    return list(query)


def list_teams_for_user(user_id, roles=None, group_ids=None, active_only=True):
    """Return teams where a user has an active team membership."""
    query = (
        Team
        .select(Team)
        .join(TeamUser)
        .where(
            (TeamUser.user == user_id)
            & (TeamUser.active == True)
            & (Team.deleted == False)
        )
        .order_by(Team.id.asc())
    )
    if active_only:
        query = query.where(Team.active == True)
    if roles is not None:
        query = query.where(TeamUser.role.in_(roles))
    if group_ids is not None:
        if not group_ids:
            return []
        query = query.where(Team.group.in_(group_ids))
    return list(query)


def list_user_team_memberships(user_ids, group_ids=None):
    """Load current memberships and team/group names together for a set of users."""
    if not user_ids or group_ids == []:
        return []
    query = (
        TeamUser.select(TeamUser, Team, Group)
        .join(Team)
        .join(Group, JOIN.LEFT_OUTER)
        .where(
            TeamUser.user.in_(user_ids),
            TeamUser.active == True,
            Team.deleted == False,
            Team.group.is_null(True) | (Group.deleted == False),
        )
        .order_by(Team.name, Team.id)
    )
    if group_ids is not None:
        query = query.where(Team.group.in_(group_ids))
    return list(query)


def get_team(team_id, include_deleted=False):
    """Return a team by id."""
    query = Team.select().where(Team.id == team_id)
    if not include_deleted:
        query = query.where(Team.deleted == False)
    return query.get()


def get_team_by_slug(slug):
    """Return a team by slug."""
    return Team.get_or_none(
        (Team.slug == slug)
        & (Team.deleted == False)
    )


def list_team_users(team_id):
    """Return users assigned to a team."""
    return list(
        TeamUser.select()
        .where(TeamUser.team == team_id)
        .order_by(TeamUser.id.asc())
    )


def get_user_team_role(user_id, team_id):
    """Return the role a user has in an active team membership."""
    membership = (
        TeamUser
        .select(TeamUser)
        .where(
            (TeamUser.user == user_id)
            & (TeamUser.team == team_id)
            & (TeamUser.active == True)
        )
        .first()
    )
    return membership.role if membership else None


def add_user_to_team(team_id, user_id, role=TEAM_VIEWER_ROLE, active=True):
    """Add a user to a team or update existing membership."""
    membership, created = TeamUser.get_or_create(
        team=team_id,
        user=user_id,
        defaults={
            "role": role,
            "active": active,
        },
    )
    if not created:
        membership.role = role
        membership.active = active
        membership.save()
    if not active:
        deactivate_user_in_team_rotations(
            team_id=membership.team.id,
            user_id=membership.user.id,
        )

    return membership


def get_team_membership(membership_id):
    """Return a team membership by id."""
    return TeamUser.get_by_id(membership_id)


def update_team_membership(membership_id, role, active=True):
    """Update a team membership."""
    membership = get_team_membership(membership_id)

    with database_proxy.atomic():
        membership.role = role
        membership.active = active
        membership.save()

        if not active:
            deactivate_user_in_team_rotations(
                team_id=membership.team.id,
                user_id=membership.user.id,
            )

    return membership


def delete_team_membership(membership_id: int) -> dict:
    """Permanently remove user from team and from all rotations of this team."""
    membership = get_team_membership(membership_id)
    team_id = membership.team.id
    group_id = membership.team.group_id
    user_id = membership.user.id

    with database_proxy.atomic():
        rotation_ids_query = (
            Rotation
            .select(Rotation.id)
            .where(Rotation.team == team_id)
        )

        layer_ids_query = (
            RotationLayer
            .select(RotationLayer.id)
            .where(RotationLayer.rotation.in_(rotation_ids_query))
        )

        removed_rotation_layer_members = (
            RotationLayerMember
            .delete()
            .where(
                (RotationLayerMember.user == user_id)
                & (RotationLayerMember.layer.in_(layer_ids_query))
            )
            .execute()
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

        removed_rotation_overrides = (
            RotationOverride
            .delete()
            .where(
                (RotationOverride.user == user_id)
                & (RotationOverride.rotation.in_(rotation_ids_query))
            )
            .execute()
        )

        membership.delete_instance()

    return {
        "id": membership_id,
        "team_id": team_id,
        "group_id": group_id,
        "user_id": user_id,
        "removed_rotation_members": removed_rotation_members,
        "removed_rotation_layer_members": removed_rotation_layer_members,
        "removed_rotation_overrides": removed_rotation_overrides,
    }


def deactivate_user_in_team_rotations(team_id: int, user_id: int) -> dict:
    """Deactivate user inside all rotations and layers of one team."""
    rotation_ids_query = (
        Rotation
        .select(Rotation.id)
        .where(Rotation.team == team_id)
    )

    layer_ids_query = (
        RotationLayer
        .select(RotationLayer.id)
        .where(RotationLayer.rotation.in_(rotation_ids_query))
    )

    disabled_rotation_layer_members = (
        RotationLayerMember
        .update(active=False)
        .where(
            (RotationLayerMember.user == user_id)
            & (RotationLayerMember.layer.in_(layer_ids_query))
            & (RotationLayerMember.active == True)
        )
        .execute()
    )

    disabled_rotation_members = (
        RotationMember
        .update(active=False)
        .where(
            (RotationMember.user == user_id)
            & (RotationMember.rotation.in_(rotation_ids_query))
            & (RotationMember.active == True)
        )
        .execute()
    )

    removed_rotation_overrides = (
        RotationOverride
        .delete()
        .where(
            (RotationOverride.user == user_id)
            & (RotationOverride.rotation.in_(rotation_ids_query))
        )
        .execute()
    )

    return {
        "disabled_rotation_members": disabled_rotation_members,
        "disabled_rotation_layer_members": disabled_rotation_layer_members,
        "removed_rotation_overrides": removed_rotation_overrides,
    }
