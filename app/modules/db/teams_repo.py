
from app.api.schemas.roles import TEAM_VIEWER_ROLE
from app.db import database_proxy
from app.modules.db.models import (
    AlertRoute,
    AlertRouteChannel,
    NotificationChannel,
    Rotation,
    RotationMember,
    RotationOverride,
    RotationLayer,
    RotationLayerMember,
    RotationLayerRestriction,
    Silence,
    Team,
    TeamUser,
)
from app.modules.common import utc_now


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


def create_team(
    slug,
    name,
    description=None,
    escalation_enabled=True,
    escalation_after_reminders=2,
    group_id=None,
    active=True,
):
    """Create a team."""
    return Team.create(
        group=group_id,
        slug=slug,
        name=name,
        description=description,
        escalation_enabled=escalation_enabled,
        escalation_after_reminders=escalation_after_reminders,
        active=active,
    )


def create_team_if_missing(slug, name, description=None, escalation_enabled=True, escalation_after_reminders=2, group_id=None):
    """Create a team if it does not exist."""
    team, _ = Team.get_or_create(
        slug=slug,
        defaults={
            "name": name,
            "group": group_id,
            "description": description,
            "escalation_enabled": escalation_enabled,
            "escalation_after_reminders": escalation_after_reminders,
        },
    )
    if team.deleted:
        team.deleted = False
        team.deleted_at = None
        team.active = True
        team.save()
    return team


def update_team(team_id, data):
    """Update a team."""
    team = get_team(team_id)
    for field in ["group", "slug", "name", "description", "escalation_enabled", "escalation_after_reminders", "active"]:
        if field in data:
            setattr(team, field, data[field])
    team.save()
    return team


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


def remove_team(team_id: int):
    """Remove a team from management UI and disable all resources under it."""
    return soft_delete_team(team_id)


def soft_delete_team(team_id: int):
    """Soft-delete a team and all resources under it."""
    now = utc_now()
    team = get_team(team_id)

    with Team._meta.database.atomic():
        rotation_ids_query = (
            Rotation
            .select(Rotation.id)
            .where(Rotation.team == team.id)
        )
        rotation_ids = [
            rotation.id
            for rotation in (
                Rotation
                .select(Rotation.id)
                .where(Rotation.team == team.id)
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
        route_ids_query = (
            AlertRoute
            .select(AlertRoute.id)
            .where(AlertRoute.team == team.id)
        )
        channel_ids_query = (
            NotificationChannel
            .select(NotificationChannel.id)
            .where(NotificationChannel.team == team.id)
        )

        RotationMember.delete().where(
            RotationMember.rotation.in_(rotation_ids_query)
        ).execute()
        RotationOverride.delete().where(
            RotationOverride.rotation.in_(rotation_ids_query)
        ).execute()
        AlertRouteChannel.delete().where(
            (AlertRouteChannel.route.in_(route_ids_query))
            | (AlertRouteChannel.channel.in_(channel_ids_query))
        ).execute()
        TeamUser.delete().where(
            TeamUser.team == team.id
        ).execute()

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

        team.active = False
        team.deleted = True
        team.deleted_at = now
        team.save()

    return team


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
