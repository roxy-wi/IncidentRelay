from app.api.schemas.roles import TEAM_VIEWER_ROLE
from app.db import database_proxy
from app.modules.db.models import (
    AlertRoute,
    Rotation,
    RotationMember,
    RotationOverride,
    RotationLayer,
    RotationLayerMember,
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
    """Create a team or restore a deleted row in the same group."""
    existing = Team.get_or_none(Team.slug == slug)
    if (
        existing is not None
        and existing.deleted
        and existing.group_id == group_id
    ):
        existing.name = name
        existing.description = description
        existing.escalation_enabled = escalation_enabled
        existing.escalation_after_reminders = escalation_after_reminders
        existing.active = active
        existing.deleted = False
        existing.deleted_at = None
        existing.save()
        return existing

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
    """Create, restore, or return a team by global slug."""
    existing = Team.get_or_none(Team.slug == slug)
    if existing is not None:
        if existing.deleted and existing.group_id == group_id:
            return create_team(
                slug=slug,
                name=name,
                description=description,
                escalation_enabled=escalation_enabled,
                escalation_after_reminders=escalation_after_reminders,
                group_id=group_id,
                active=True,
            )
        return existing
    return create_team(
        slug=slug,
        name=name,
        description=description,
        escalation_enabled=escalation_enabled,
        escalation_after_reminders=escalation_after_reminders,
        group_id=group_id,
        active=True,
    )


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
    """Soft-delete a team and stop all team-owned operational state."""
    from app.modules.db import (
        calendar_feeds_repo,
        channels_repo,
        escalation_policies_repo,
        heartbeats_repo,
        maintenance_repo,
        matcher_presets_repo,
        notification_policies_repo,
        priority_policies_repo,
        rotations_repo,
        routes_repo,
        services_repo,
        silences_repo,
    )
    from app.modules.db.models import (
        ApiToken,
        BusinessService,
        CalendarFeed,
        EscalationPolicy,
        Heartbeat,
        MaintenanceWindow,
        MatcherPreset,
        NotificationChannel,
        NotificationPolicy,
        PriorityPolicy,
        Rotation,
        Service,
        Silence,
    )
    from app.modules.db.soft_delete_hardening import (
        deactivate_sso_mappings,
        resolve_team_runtime_alerts,
    )

    now = utc_now()
    team = get_team(team_id)

    with Team._meta.database.atomic():
        resolve_team_runtime_alerts(team.id, now=now)

        for heartbeat in list(Heartbeat.select().where(
            (Heartbeat.team == team.id) & (Heartbeat.deleted == False)  # noqa: E712
        )):
            heartbeats_repo.soft_delete_heartbeat(heartbeat)

        for service in list(Service.select().where(
            (Service.team == team.id) & (Service.deleted == False)  # noqa: E712
        )):
            services_repo.soft_delete_service(service.id)

        for route in list(AlertRoute.select().where(
            (AlertRoute.team == team.id) & (AlertRoute.deleted == False)  # noqa: E712
        )):
            routes_repo.soft_delete_route(route.id)

        for rotation in list(Rotation.select().where(
            (Rotation.team == team.id) & (Rotation.deleted == False)  # noqa: E712
        )):
            rotations_repo.soft_delete_rotation(rotation.id)

        for channel in list(NotificationChannel.select().where(
            (NotificationChannel.team == team.id)
            & (NotificationChannel.deleted == False)  # noqa: E712
        )):
            channels_repo.delete_channel(channel.id)

        for policy in list(EscalationPolicy.select().where(
            (EscalationPolicy.team == team.id) & (EscalationPolicy.deleted == False)  # noqa: E712
        )):
            escalation_policies_repo.soft_delete_policy(policy.id)

        for policy in list(NotificationPolicy.select().where(
            (NotificationPolicy.team == team.id) & (NotificationPolicy.deleted == False)  # noqa: E712
        )):
            notification_policies_repo.soft_delete_notification_policy(policy.id)

        for policy in list(PriorityPolicy.select().where(
            (PriorityPolicy.team == team.id) & (PriorityPolicy.deleted == False)  # noqa: E712
        )):
            priority_policies_repo.soft_delete_priority_policy(policy.id)

        for preset in list(MatcherPreset.select().where(
            (MatcherPreset.team == team.id) & (MatcherPreset.deleted == False)  # noqa: E712
        )):
            matcher_presets_repo.soft_delete_matcher_preset(preset.id)

        for silence in list(Silence.select().where(
            (Silence.team == team.id) & (Silence.deleted == False)  # noqa: E712
        )):
            silences_repo.soft_delete_silence(silence.id)

        for feed in list(CalendarFeed.select().where(
            (CalendarFeed.team == team.id) & (CalendarFeed.deleted == False)  # noqa: E712
        )):
            calendar_feeds_repo.soft_delete_calendar_feed(feed)

        for window in list(MaintenanceWindow.select().where(
            (MaintenanceWindow.team == team.id)
            & (MaintenanceWindow.deleted == False)  # noqa: E712
        )):
            maintenance_repo.soft_delete_maintenance_window(window)

        # Business services are group-owned; deleting their owner team must not
        # delete the business service itself.
        BusinessService.update(owner_team=None, updated_at=now).where(
            BusinessService.owner_team == team.id
        ).execute()

        TeamUser.delete().where(TeamUser.team == team.id).execute()
        ApiToken.update(
            active=False, deleted=True, deleted_at=now
        ).where(
            (ApiToken.team == team.id)
            & (ApiToken.deleted == False)  # noqa: E712
        ).execute()

        deactivate_sso_mappings(team_id=team.id)

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
