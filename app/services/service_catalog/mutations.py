"""Service and dependency mutations with catalog ownership and graph invalidation.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from app.modules.common import utc_now
from app.modules.db import services_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertRoute,
    BusinessServiceComponent,
    EventOrchestration,
    Heartbeat,
    Service,
    ServiceChannel,
    ServiceDependency,
    ServiceLink,
    ServiceMatchRule,
    ServiceOwner,
    ServiceReadinessState,
    ServiceRunbook,
    ServiceSli,
    ServiceSlo,
    Team,
)


def restore_service(service_id, data):
    """Restore and reconfigure a soft-deleted service."""

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(service_id=service_id, team_id=data.get("team")):
        service = services_repo.get_service(service_id, include_deleted=True)

        if "team" in data:
            team = Team.get_by_id(data["team"])
            data["group"] = team.group_id

        for field, value in data.items():
            setattr(service, field, value)

        service.deleted = False
        service.deleted_at = None
        service.updated_at = utc_now()
        service.save()

        return service


def create_service(data):
    """Create or restore a service."""

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(team_id=data["team"]):
        data = dict(data)
        team = Team.get_by_id(data["team"])

        if not data.get("group"):
            data["group"] = team.group_id

        existing = services_repo.get_service_by_team_and_slug(
            data["team"],
            data["slug"],
            include_deleted=True,
        )

        if existing and existing.deleted:
            return restore_service(existing.id, data)

        data["updated_at"] = utc_now()

        return Service.create(**data)


def update_service(service_id, data):
    """Update a service."""

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(service_id=service_id, team_id=data.get("team")):
        service = services_repo.get_service(service_id)
        from app.services.authorization import recheck_team_write

        recheck_team_write(service.team_id, destination_team_id=data.get("team"))

        if "team" in data:
            team = Team.get_by_id(data["team"])
            data["group"] = team.group_id

        for field, value in data.items():
            setattr(service, field, value)

        service.updated_at = utc_now()
        service.save()

        return service


def soft_delete_service(service_id):
    """Soft-delete a service and stop service-owned operational state."""

    from app.services.change_intelligence.catalog import catalog_authorization_change

    with catalog_authorization_change(service_id=service_id):
        from app.modules.db import orchestrations_repo
        from app.modules.db.soft_delete_hardening import (
            cancel_pending_orchestration_work,
        )

        service = services_repo.get_service(service_id)
        now = utc_now()
        database = Service._meta.database

        with database.atomic():
            orchestration_ids = [
                row.id
                for row in EventOrchestration.select(EventOrchestration.id).where(
                    (EventOrchestration.service == service.id)
                    & (EventOrchestration.deleted == False)  # noqa: E712
                )
            ]

            # Cancel before detaching AlertGroup.service. Global orchestration work
            # is associated with the service through the alert group rather than
            # EventOrchestration.service.
            cancel_pending_orchestration_work(
                service_id=service.id,
                orchestration_ids=orchestration_ids,
                now=now,
                reason="service_deleted",
            )

            for orchestration_id in orchestration_ids:
                orchestrations_repo.archive_orchestration(orchestration_id)

            orchestrations_repo.revoke_intake_tokens_for_scope(
                service_id=service.id,
                now=now,
            )

            # Prevent current incidents from silently inheriting configuration if
            # this service row is restored later. Historical resolved incidents keep
            # their original service reference.
            Alert.update(service=None).where(
                (Alert.service == service.id) & (Alert.status != "resolved")
            ).execute()
            AlertGroup.update(service=None, updated_at=now).where(
                (AlertGroup.service == service.id)
                & (~AlertGroup.status.in_(("resolved", "merged")))
            ).execute()
            AlertRoute.update(service=None).where(
                AlertRoute.service == service.id
            ).execute()
            Heartbeat.update(service=None, updated_at=now).where(
                Heartbeat.service == service.id
            ).execute()

            ServiceMatchRule.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
                updated_at=now,
            ).where(
                (ServiceMatchRule.service == service.id)
                & (ServiceMatchRule.deleted == False)  # noqa: E712
            ).execute()
            ServiceRunbook.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
                updated_at=now,
            ).where(
                (ServiceRunbook.service == service.id)
                & (ServiceRunbook.deleted == False)  # noqa: E712
            ).execute()
            ServiceLink.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
                updated_at=now,
            ).where(
                (ServiceLink.service == service.id) & (ServiceLink.deleted == False)  # noqa: E712
            ).execute()
            ServiceDependency.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
                updated_at=now,
            ).where(
                (
                    (ServiceDependency.service == service.id)
                    | (ServiceDependency.depends_on_service == service.id)
                )
                & (ServiceDependency.deleted == False)  # noqa: E712
            ).execute()
            # Active/derived state must be rebuilt explicitly after a restore.
            ServiceChannel.delete().where(
                ServiceChannel.service == service.id
            ).execute()
            ServiceReadinessState.delete().where(
                ServiceReadinessState.service == service.id
            ).execute()
            ServiceOwner.update(active=False).where(
                ServiceOwner.service == service.id
            ).execute()
            ServiceSlo.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
                updated_at=now,
            ).where(
                (ServiceSlo.service == service.id) & (ServiceSlo.deleted == False)  # noqa: E712
            ).execute()
            ServiceSli.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
                updated_at=now,
            ).where(
                (ServiceSli.service == service.id) & (ServiceSli.deleted == False)  # noqa: E712
            ).execute()
            BusinessServiceComponent.update(
                deleted=True,
                deleted_at=now,
                enabled=False,
                updated_at=now,
            ).where(
                (BusinessServiceComponent.service == service.id)
                & (BusinessServiceComponent.deleted == False)  # noqa: E712
            ).execute()

            service.enabled = False
            service.deleted = True
            service.deleted_at = now
            service.updated_at = now
            service.save()

        return service


def create_service_dependency(service_id, data):
    """Create or restore a service dependency."""
    from app.services.change_intelligence.catalog import graph_change

    with graph_change():
        return services_repo._create_service_dependency(service_id, data)


def update_service_dependency(dependency_id, data):
    """Update a service dependency."""
    from app.services.change_intelligence.catalog import graph_change

    with graph_change():
        dependency = services_repo.get_service_dependency(dependency_id)
        for field, value in data.items():
            setattr(dependency, field, value)
        dependency.updated_at = utc_now()
        dependency.save()
        return dependency


def soft_delete_service_dependency(dependency_id):
    """Soft-delete a service dependency."""
    from app.services.change_intelligence.catalog import graph_change

    with graph_change():
        dependency = services_repo.get_service_dependency(dependency_id)
        dependency.enabled = False
        dependency.deleted = True
        dependency.deleted_at = utc_now()
        dependency.updated_at = utc_now()
        dependency.save()
        return dependency
