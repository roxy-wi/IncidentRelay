from datetime import datetime

from app.models import AlertRoute, AlertRouteChannel, Group, Team


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
    matchers=None,
    group_by=None,
    enabled=True,
    intake_token_prefix=None,
    intake_token_hash=None,
):
    """
    Create an alert route.
    """

    return AlertRoute.create(
        team=team_id,
        name=name,
        source=source,
        rotation=rotation_id,
        matchers=matchers or {},
        group_by=group_by or [],
        enabled=enabled,
        intake_token_prefix=intake_token_prefix,
        intake_token_hash=intake_token_hash,
    )


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
        "matchers",
        "group_by",
        "enabled",
        "intake_token_prefix",
        "intake_token_hash",
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


def disable_route(route_id):
    """
    Soft-delete a route without removing historical alert references.
    """

    return soft_delete_route(route_id)


def soft_delete_route(route_id):
    """
    Soft-delete a route without removing historical alert references.
    """

    route = get_route(route_id)
    route.enabled = False
    route.deleted = True
    route.deleted_at = datetime.utcnow()
    route.save()
    return route


def delete_route(route_id):
    """
    Soft-delete a route and unlink its channels.
    """

    AlertRouteChannel.delete().where(AlertRouteChannel.route == route_id).execute()
    return soft_delete_route(route_id)


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
