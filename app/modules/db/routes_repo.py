from datetime import datetime

from app.modules.db.models import AlertRoute, AlertRouteChannel, Group, Team


def list_routes(team_id=None, team_ids=None, enabled_only=False, source=None, active_only=True, include_deleted=False):
    """
    Return alert routes.
    """

    query = (
        AlertRoute
        .select(AlertRoute)
        .join(Team, on=(AlertRoute.team == Team.id))
        .switch(AlertRoute)
        .order_by(AlertRoute.id.asc())
    )

    if not include_deleted:
        query = query.where(AlertRoute.deleted == False)

    if active_only:
        query = query.where(
            (Team.active == True)
            & (Team.deleted == False)
        )
        query = (
            query
            .join(Group, on=(Team.group == Group.id))
            .where(
                (Group.active == True)
                & (Group.deleted == False)
            )
            .switch(AlertRoute)
        )

    if team_id:
        query = query.where(AlertRoute.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return []
        query = query.where(AlertRoute.team.in_(team_ids))

    if source:
        query = query.where(AlertRoute.source == source)

    if enabled_only:
        query = query.where(AlertRoute.enabled == True)

    return list(query)


def get_route(route_id, include_deleted=False):
    """
    Return a route by id.
    """

    query = AlertRoute.select().where(AlertRoute.id == route_id)

    if not include_deleted:
        query = query.where(AlertRoute.deleted == False)

    return query.get()


def get_route_by_team_and_name(
    team_id,
    name,
    *,
    exclude_route_id=None,
    include_deleted=True,
):
    """
    Return a route with the same name in the same team.

    Deleted routes are included by default because they continue
    occupying the unique database key.
    """
    query = AlertRoute.select().where(
        (AlertRoute.team == team_id)
        & (AlertRoute.name == name)
    )

    if exclude_route_id is not None:
        query = query.where(
            AlertRoute.id != exclude_route_id
        )

    if not include_deleted:
        query = query.where(
            AlertRoute.deleted == False
        )

    return query.first()


def get_route_by_intake_hash(token_hash):
    """
    Return an enabled route by alert intake token hash.
    """

    if not token_hash:
        return None

    return (
        AlertRoute
        .select(AlertRoute)
        .join(Team, on=(AlertRoute.team == Team.id))
        .switch(AlertRoute)
        .join(Group, on=(Team.group == Group.id))
        .switch(AlertRoute)
        .where(
            (AlertRoute.intake_token_hash == token_hash)
            & (AlertRoute.enabled == True)
            & (AlertRoute.deleted == False)
            & (Team.active == True)
            & (Team.deleted == False)
            & (Group.active == True)
            & (Group.deleted == False)
        )
        .first()
    )


def create_route(
    team_id,
    name,
    source,
    rotation_id=None,
    escalation_policy_id=None,
    matcher_preset_id=None,
    matchers=None,
    group_by=None,
    enabled=True,
    intake_token_prefix=None,
    intake_token_hash=None,
    service_id=None,
    integration_config=None,
    notification_channel_mode="route_only",
):
    """Create an alert route."""
    return AlertRoute.create(
        team=team_id,
        name=name,
        source=source,
        rotation=rotation_id,
        escalation_policy=escalation_policy_id,
        service=service_id,
        matcher_preset=matcher_preset_id,
        matchers=matchers or {},
        group_by=group_by or [],
        enabled=enabled,
        intake_token_prefix=intake_token_prefix,
        intake_token_hash=intake_token_hash,
        integration_config=integration_config or {},
        notification_channel_mode=notification_channel_mode,
    )


def restore_route(
    route_id,
    *,
    team_id,
    name,
    source,
    rotation_id=None,
    escalation_policy_id=None,
    matcher_preset_id=None,
    matchers=None,
    group_by=None,
    enabled=True,
    intake_token_prefix=None,
    intake_token_hash=None,
    service_id=None,
    integration_config=None,
    notification_channel_mode="route_only",
):
    """Restore and completely reconfigure a deleted route."""
    route = get_route(
        route_id,
        include_deleted=True,
    )

    route.team = team_id
    route.name = name
    route.source = source
    route.rotation = rotation_id
    route.escalation_policy = escalation_policy_id
    route.matcher_preset = matcher_preset_id
    route.matchers = matchers or {}
    route.group_by = group_by or []
    route.enabled = enabled
    route.intake_token_prefix = intake_token_prefix
    route.intake_token_hash = intake_token_hash
    route.service = service_id
    route.integration_config = integration_config or {}
    route.notification_channel_mode = notification_channel_mode
    route.deleted = False
    route.deleted_at = None

    route.save()

    return route


def create_route_if_missing(team_id, name, source, rotation_id=None, matchers=None, group_by=None):
    """
    Create an alert route if missing.
    """

    route, _ = AlertRoute.get_or_create(
        team=team_id,
        name=name,
        defaults={
            "source": source,
            "rotation": rotation_id,
            "matchers": matchers or {},
            "group_by": group_by or [],
        },
    )

    if route.deleted:
        route.deleted = False
        route.deleted_at = None
        route.enabled = True
        route.save()

    return route


def update_route(route_id, data):
    """
    Update a route.
    """

    route = get_route(route_id)

    for field in [
        "team",
        "name",
        "source",
        "rotation",
        "escalation_policy",
        "matcher_preset",
        "matchers",
        "group_by",
        "enabled",
        "intake_token_prefix",
        "intake_token_hash",
        "service",
        "integration_config",
        "notification_channel_mode",
    ]:
        if field in data:
            setattr(route, field, data[field])

    route.save()
    return route


def set_route_intake_token(route_id, token_prefix, token_hash):
    """
    Store a new alert intake token for a route.
    """

    route = get_route(route_id)
    route.intake_token_prefix = token_prefix
    route.intake_token_hash = token_hash
    route.save()
    return route


def set_route_enabled(route_id, enabled):
    """
    Enable or disable a route without deleting it.

    Disabled routes stay visible in route management UI and can be enabled
    again later. Alert intake only uses enabled routes.
    """
    route = get_route(route_id)
    route.enabled = enabled
    route.save()

    return route


def disable_route(route_id):
    """
    Disable a route without deleting it.
    """
    return set_route_enabled(route_id, False)


def enable_route(route_id):
    """
    Enable a previously disabled route.
    """
    return set_route_enabled(route_id, True)


def soft_delete_route(route_id):
    """
    Soft-delete a route without removing historical alert references.

    Deleted routes are hidden from active route lists. Historical alerts keep
    their route reference.
    """
    route = get_route(route_id)

    route.enabled = False
    route.deleted = True
    route.deleted_at = datetime.utcnow()
    route.save()

    AlertRouteChannel.delete().where(
        AlertRouteChannel.route == route_id
    ).execute()

    return route


def list_route_channels(route_id):
    """
    Return route-channel links.
    """

    return list(AlertRouteChannel.select().where(AlertRouteChannel.route == route_id))


def replace_route_channels(route_id, channel_ids):
    """
    Replace all channel links for a route.
    """

    AlertRouteChannel.delete().where(AlertRouteChannel.route == route_id).execute()
    return [link_route_channel(route_id, channel_id) for channel_id in channel_ids]


def link_route_channel(route_id, channel_id):
    """
    Link a route to a notification channel.
    """

    link, _ = AlertRouteChannel.get_or_create(route=route_id, channel=channel_id)
    return link


def unlink_route_channel(route_id, channel_id):
    """
    Remove a channel from a route.
    """

    return AlertRouteChannel.delete().where(
        (AlertRouteChannel.route == route_id) & (AlertRouteChannel.channel == channel_id)
    ).execute()
