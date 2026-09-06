
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
    """Create a group or restore the deleted row occupying its slug."""
    existing = Group.get_or_none(Group.slug == slug)
    if existing is not None and existing.deleted:
        existing.name = name
        existing.description = description
        existing.active = active
        existing.deleted = False
        existing.deleted_at = None
        existing.save()
        return existing

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
    """Soft-delete a group and stop all active resources owned by it."""
    from app.modules.db import (
        business_services_repo,
        channels_repo,
        maintenance_repo,
        orchestrations_repo,
        teams_repo,
    )
    from app.modules.db.models import (
        BusinessService,
        EventOrchestration,
        MaintenanceWindow,
        NotificationChannel,
        OrchestrationWebhookAction,
        ServiceStandard,
    )
    from app.modules.db.soft_delete_hardening import (
        cancel_pending_orchestration_work,
        deactivate_sso_mappings,
    )
    from app.services.service_catalog.standards import delete_service_standard

    now = utc_now()
    with db.atomic():
        group = get_group(group_id)

        # Team deletion owns all team-scoped cascades (services, policies,
        # routes, heartbeats, calendars, memberships and tokens).
        teams = list(
            Team.select().where(
                (Team.group == group.id)
                & (Team.deleted == False)  # noqa: E712
            )
        )
        for team in teams:
            teams_repo.soft_delete_team(team.id)

        for business_service in list(
            BusinessService.select().where(
                (BusinessService.group == group.id)
                & (BusinessService.deleted == False)  # noqa: E712
            )
        ):
            business_services_repo.soft_delete_business_service(business_service.id)

        for standard in list(
            ServiceStandard.select().where(
                (ServiceStandard.group == group.id)
                & (ServiceStandard.deleted == False)  # noqa: E712
            )
        ):
            delete_service_standard(standard)

        for window in list(
            MaintenanceWindow.select().where(
                (MaintenanceWindow.group == group.id)
                & (MaintenanceWindow.deleted == False)  # noqa: E712
            )
        ):
            maintenance_repo.soft_delete_maintenance_window(window)

        # Group-only channels are not reached through team deletion.
        for channel in list(
            NotificationChannel.select().where(
                (NotificationChannel.group == group.id)
                & NotificationChannel.team.is_null(True)
                & (NotificationChannel.deleted == False)  # noqa: E712
            )
        ):
            channels_repo.delete_channel(channel.id)

        orchestrations = list(
            EventOrchestration.select(EventOrchestration.id).where(
                (EventOrchestration.group == group.id)
                & (EventOrchestration.deleted == False)  # noqa: E712
            )
        )
        for orchestration in orchestrations:
            orchestrations_repo.archive_orchestration(orchestration.id)

        orchestrations_repo.revoke_intake_tokens_for_scope(
            group_id=group.id,
            now=now,
        )

        action_ids = [
            row.id for row in OrchestrationWebhookAction.select(
                OrchestrationWebhookAction.id
            ).where(
                (OrchestrationWebhookAction.group == group.id)
                & (OrchestrationWebhookAction.deleted == False)  # noqa: E712
            )
        ]
        if action_ids:
            OrchestrationWebhookAction.update(
                enabled=False,
                deleted=True,
                deleted_at=now,
                updated_at=now,
            ).where(OrchestrationWebhookAction.id.in_(action_ids)).execute()

        cancel_pending_orchestration_work(
            group_id=group.id,
            now=now,
            reason="group_deleted",
        )
        deactivate_sso_mappings(group_id=group.id)

        UserGroup.update(active=False).where(UserGroup.group == group.id).execute()
        User.update(active_group=None).where(User.active_group == group.id).execute()
        ApiToken.update(
            deleted=True,
            deleted_at=now,
            active=False,
        ).where(
            (ApiToken.group == group.id)
            & (ApiToken.deleted == False)  # noqa: E712
        ).execute()

        group.deleted = True
        group.deleted_at = now
        group.active = False
        group.save()

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
