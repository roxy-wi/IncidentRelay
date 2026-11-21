"""Group lifecycle operations and atomic catalog invalidation.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import groups_repo
from app.modules.db.models import (
    ApiToken,
    Group,
    Team,
    User,
    UserGroup,
)
from app.services import team_management


def create_group(slug, name, description=None, active=True):
    """Create a group or restore the deleted row occupying its slug."""

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(group_slug=slug):
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

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(group_id=group_id):
        group = groups_repo.get_group(group_id)
        for field in ["slug", "name", "description", "active"]:
            if field in data:
                setattr(group, field, data[field])
        group.save()
        return group


def soft_delete_group(group_id):
    """Soft-delete a group and stop all active resources owned by it."""

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(group_id=group_id):
        from app.modules.db import (
            business_services_repo,
            channels_repo,
            maintenance_repo,
            orchestrations_repo,
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
            group = groups_repo.get_group(group_id)

            # Team deletion owns all team-scoped cascades (services, policies,
            # routes, heartbeats, calendars, memberships and tokens).
            teams = list(
                Team.select().where(
                    (Team.group == group.id) & (Team.deleted == False)  # noqa: E712
                )
            )
            for team in teams:
                team_management.soft_delete_team(team.id)

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
                row.id
                for row in OrchestrationWebhookAction.select(
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
            User.update(active_group=None).where(
                User.active_group == group.id
            ).execute()
            ApiToken.update(
                deleted=True,
                deleted_at=now,
                active=False,
            ).where(
                (ApiToken.group == group.id) & (ApiToken.deleted == False)  # noqa: E712
            ).execute()

            group.deleted = True
            group.deleted_at = now
            group.active = False
            group.save()

        return group
