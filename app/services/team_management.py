"""Team lifecycle operations with authorization inside the write transaction.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from app.modules.common import utc_now
from app.modules.db import teams_repo
from app.modules.db.models import (
    AlertRoute,
    Team,
    TeamUser,
)
from app.services import heartbeat_management, route_management
from app.services.service_catalog import mutations as service_mutations


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

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(team_slug=slug):
        existing = Team.get_or_none(Team.slug == slug)
        if existing is not None and existing.deleted and existing.group_id == group_id:
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


def create_team_if_missing(
    slug,
    name,
    description=None,
    escalation_enabled=True,
    escalation_after_reminders=2,
    group_id=None,
):
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

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(team_id=team_id):
        from app.services.authorization import recheck_team_write

        recheck_team_write(team_id, destination_group_id=data.get("group"))
        team = teams_repo.get_team(team_id)
        for field in [
            "group",
            "slug",
            "name",
            "description",
            "escalation_enabled",
            "escalation_after_reminders",
            "active",
        ]:
            if field in data:
                setattr(team, field, data[field])
        team.save()
        return team


def remove_team(team_id: int):
    """Remove a team from management UI and disable all resources under it."""
    return soft_delete_team(team_id)


def soft_delete_team(team_id: int):
    """Soft-delete a team and stop all team-owned operational state."""

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(team_id=team_id):
        from app.modules.db import (
            calendar_feeds_repo,
            channels_repo,
            escalation_policies_repo,
            maintenance_repo,
            matcher_presets_repo,
            notification_policies_repo,
            priority_policies_repo,
            rotations_repo,
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
        from app.modules.db.soft_delete_hardening import deactivate_sso_mappings
        from app.services.alerts.resource_deletion import resolve_team_runtime_alerts

        now = utc_now()
        team = teams_repo.get_team(team_id)

        with Team._meta.database.atomic():
            resolve_team_runtime_alerts(team.id, now=now)

            for heartbeat in list(
                Heartbeat.select().where(
                    (Heartbeat.team == team.id) & (Heartbeat.deleted == False)  # noqa: E712
                )
            ):
                heartbeat_management.soft_delete_heartbeat(heartbeat)

            for service in list(
                Service.select().where(
                    (Service.team == team.id) & (Service.deleted == False)  # noqa: E712
                )
            ):
                service_mutations.soft_delete_service(service.id)

            for route in list(
                AlertRoute.select().where(
                    (AlertRoute.team == team.id) & (AlertRoute.deleted == False)  # noqa: E712
                )
            ):
                route_management.soft_delete_route(route.id)

            for rotation in list(
                Rotation.select().where(
                    (Rotation.team == team.id) & (Rotation.deleted == False)  # noqa: E712
                )
            ):
                rotations_repo.soft_delete_rotation(rotation.id)

            for channel in list(
                NotificationChannel.select().where(
                    (NotificationChannel.team == team.id)
                    & (NotificationChannel.deleted == False)  # noqa: E712
                )
            ):
                channels_repo.delete_channel(channel.id)

            for policy in list(
                EscalationPolicy.select().where(
                    (EscalationPolicy.team == team.id)
                    & (EscalationPolicy.deleted == False)  # noqa: E712
                )
            ):
                escalation_policies_repo.soft_delete_policy(policy.id)

            for policy in list(
                NotificationPolicy.select().where(
                    (NotificationPolicy.team == team.id)
                    & (NotificationPolicy.deleted == False)  # noqa: E712
                )
            ):
                notification_policies_repo.soft_delete_notification_policy(policy.id)

            for policy in list(
                PriorityPolicy.select().where(
                    (PriorityPolicy.team == team.id) & (PriorityPolicy.deleted == False)  # noqa: E712
                )
            ):
                priority_policies_repo.soft_delete_priority_policy(policy.id)

            for preset in list(
                MatcherPreset.select().where(
                    (MatcherPreset.team == team.id) & (MatcherPreset.deleted == False)  # noqa: E712
                )
            ):
                matcher_presets_repo.soft_delete_matcher_preset(preset.id)

            for silence in list(
                Silence.select().where(
                    (Silence.team == team.id) & (Silence.deleted == False)  # noqa: E712
                )
            ):
                silences_repo.soft_delete_silence(silence.id)

            for feed in list(
                CalendarFeed.select().where(
                    (CalendarFeed.team == team.id) & (CalendarFeed.deleted == False)  # noqa: E712
                )
            ):
                calendar_feeds_repo.soft_delete_calendar_feed(feed)

            for window in list(
                MaintenanceWindow.select().where(
                    (MaintenanceWindow.team == team.id)
                    & (MaintenanceWindow.deleted == False)  # noqa: E712
                )
            ):
                maintenance_repo.soft_delete_maintenance_window(window)

            # Business services are group-owned; deleting their owner team must not
            # delete the business service itself.
            BusinessService.update(owner_team=None, updated_at=now).where(
                BusinessService.owner_team == team.id
            ).execute()

            TeamUser.delete().where(TeamUser.team == team.id).execute()
            ApiToken.update(active=False, deleted=True, deleted_at=now).where(
                (ApiToken.team == team.id) & (ApiToken.deleted == False)  # noqa: E712
            ).execute()

            deactivate_sso_mappings(team_id=team.id)

            team.active = False
            team.deleted = True
            team.deleted_at = now
            team.save()

        return team
