"""Route deletion, including termination of associated heartbeat lifecycles.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from app.modules.common import utc_now
from app.modules.db import routes_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertRoute,
    AlertRouteChannel,
    Heartbeat,
    MaintenanceWindowScope,
    ServiceMatchRule,
)
from app.services import heartbeat_management


def soft_delete_route(route_id):
    """Soft-delete a route and stop route-owned active configuration."""
    from app.modules.db.soft_delete_hardening import cancel_pending_orchestration_work

    route = routes_repo.get_route(route_id)
    now = utc_now()
    database = AlertRoute._meta.database

    with database.atomic():
        # Cancel before detaching AlertGroup.route so global/service
        # orchestration work can still be matched through the alert group.
        cancel_pending_orchestration_work(
            route_id=route.id,
            now=now,
            reason="route_deleted",
        )

        # Active incidents must not start using a newly restored route later.
        Alert.update(route=None).where(
            (Alert.route == route.id) & (Alert.status != "resolved")
        ).execute()
        AlertGroup.update(route=None, updated_at=now).where(
            (AlertGroup.route == route.id)
            & (~AlertGroup.status.in_(("resolved", "merged")))
        ).execute()

        for heartbeat in list(
            Heartbeat.select().where(
                (Heartbeat.route == route.id) & (Heartbeat.deleted == False)  # noqa: E712
            )
        ):
            heartbeat_management.soft_delete_heartbeat(heartbeat)

        ServiceMatchRule.update(
            enabled=False,
            deleted=True,
            deleted_at=now,
            updated_at=now,
        ).where(
            (ServiceMatchRule.route == route.id) & (ServiceMatchRule.deleted == False)  # noqa: E712
        ).execute()
        MaintenanceWindowScope.delete().where(
            MaintenanceWindowScope.route == route.id
        ).execute()
        AlertRouteChannel.delete().where(AlertRouteChannel.route == route.id).execute()

        route.enabled = False
        route.deleted = True
        route.deleted_at = now
        # Never let an old intake credential come back through an accidental
        # row restore. Explicit route restoration must provide a new token.
        route.intake_token_prefix = None
        route.intake_token_hash = None
        route.save()

    return route
