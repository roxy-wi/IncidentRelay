from peewee import IntegrityError, prefetch

from app.db import database_proxy
from app.modules.db.models import (
    AlertRoute,
    Group,
    Rotation,
    RotationMember,
    RotationOverride,
    RotationLayer,
    RotationLayerMember,
    RotationLayerRestriction,
    Team,
    TeamUser,
    User
)
from app.modules.common import utc_now


def list_rotations(
    team_id=None,
    team_ids=None,
    enabled_only=False,
    active_only=True,
    include_deleted=False,
):
    """Return rotations."""
    query = (
        Rotation
        .select(Rotation)
        .join(Team, on=(Rotation.team == Team.id))
        .switch(Rotation)
        .order_by(Rotation.id.asc())
    )

    if not include_deleted:
        query = query.where(Rotation.deleted == False)

    if active_only:
        query = query.where(
            (Team.active == True) &
            (Team.deleted == False)
        )
        query = (
            query
            .join(Group, on=(Team.group == Group.id))
            .where(
                (Group.active == True) &
                (Group.deleted == False)
            )
            .switch(Rotation)
        )

    if team_id:
        query = query.where(Rotation.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return []
        query = query.where(Rotation.team.in_(team_ids))

    if enabled_only:
        query = query.where(Rotation.enabled == True)

    return list(query)


def get_rotation(rotation_id, include_deleted=False):
    """
    Return a rotation by id.
    """

    query = Rotation.select().where(Rotation.id == rotation_id)

    if not include_deleted:
        query = query.where(Rotation.deleted == False)

    return query.get()


def create_rotation(
        team_id,
        name,
        description,
        start_at,
        duration_seconds,
        reminder_interval_seconds=300,
        rotation_type="daily",
        interval_value=1,
        interval_unit="days",
        handoff_time="09:00",
        handoff_weekday=None,
        timezone="UTC",
        enabled=True,
):
    """
    Create a rotation.
    """
    existing = (
        Rotation.select()
        .where(
            (Rotation.team == team_id)
            & (Rotation.name == name)
            & (Rotation.deleted == False)
        )
        .first()
    )

    if existing:
        raise ValueError("rotation with this name already exists in this team")

    try:
        with database_proxy.atomic():
            rotation = Rotation.create(
                team=team_id,
                name=name,
                description=description,
                start_at=start_at,
                duration_seconds=duration_seconds,
                reminder_interval_seconds=reminder_interval_seconds,
                rotation_type=rotation_type,
                interval_value=interval_value,
                interval_unit=interval_unit,
                handoff_time=handoff_time,
                handoff_weekday=handoff_weekday,
                timezone=timezone,
                enabled=enabled,
            )

            get_or_create_default_layer(rotation.id)

            return rotation

    except IntegrityError:
        raise ValueError("rotation with this name already exists in this team")


def create_rotation_if_missing(team_id, name, description, start_at, duration_seconds, reminder_interval_seconds=300, rotation_type="daily", interval_value=1, interval_unit="days", handoff_time="09:00", handoff_weekday=None, timezone="UTC"):
    """
    Create a rotation if it does not exist.
    """

    rotation, _ = Rotation.get_or_create(
        team=team_id,
        name=name,
        defaults={
            "description": description,
            "start_at": start_at,
            "duration_seconds": duration_seconds,
            "reminder_interval_seconds": reminder_interval_seconds,
            "rotation_type": rotation_type,
            "interval_value": interval_value,
            "interval_unit": interval_unit,
            "handoff_time": handoff_time,
            "handoff_weekday": handoff_weekday,
            "timezone": timezone,
        },
    )

    if rotation.deleted:
        rotation.deleted = False
        rotation.deleted_at = None
        rotation.enabled = True
        rotation.save()

    return rotation


def list_rotation_members(rotation_id: int, active_only: bool = False):
    """Return rotation members ordered by position."""
    query = RotationMember.select().where(RotationMember.rotation == rotation_id)

    if active_only:
        query = (
            query
            .join(User)
            .where(
                (RotationMember.active == True)
                & (User.active == True)
                & (User.deleted == False)
            )
        )

    return list(query.order_by(RotationMember.position.asc(), RotationMember.id.asc()))


def add_rotation_member(rotation_id, user_id, position):
    """
    Add a member to a rotation.
    """

    member, created = RotationMember.get_or_create(
        rotation=rotation_id,
        user=user_id,
        defaults={"position": position},
    )
    if not created:
        member.position = position
        member.active = True
        member.save()
    return member


def list_rotation_overrides(rotation_id, start_at=None, end_at=None, include_expired=False):
    """
    Return overrides for a rotation.
    """
    query = RotationOverride.select().where(
        RotationOverride.rotation == rotation_id
    )

    if start_at and end_at:
        query = query.where(
            (RotationOverride.starts_at < end_at)
            & (RotationOverride.ends_at > start_at)
        )
    elif not include_expired:
        query = query.where(RotationOverride.ends_at > utc_now())

    return list(query.order_by(RotationOverride.starts_at.asc(), RotationOverride.id.asc()))


def get_active_override(rotation_id, now=None):
    """
    Return the active override for a rotation.
    """

    now = now or utc_now()
    return (
        RotationOverride.select()
        .where(
            (RotationOverride.rotation == rotation_id)
            & (RotationOverride.starts_at <= now)
            & (RotationOverride.ends_at > now)
        )
        .order_by(RotationOverride.id.desc())
        .first()
    )


def create_rotation_override(rotation_id, user_id, starts_at, ends_at, reason=None):
    """
    Create a rotation override.
    """

    return RotationOverride.create(
        rotation=rotation_id,
        user=user_id,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=reason,
    )


def update_rotation(rotation_id, data):
    """
    Update a rotation.
    """

    rotation = get_rotation(rotation_id)
    for field in [
        "team",
        "name",
        "description",
        "start_at",
        "duration_seconds",
        "reminder_interval_seconds",
        "rotation_type",
        "interval_value",
        "interval_unit",
        "handoff_time",
        "handoff_weekday",
        "timezone",
        "enabled",
    ]:
        if field in data:
            setattr(rotation, field, data[field])
    rotation.save()
    return rotation


def soft_delete_rotation(rotation_id):
    """Soft-delete rotation and remove schedule data owned by it."""

    db = Rotation._meta.database

    with db.atomic():
        rotation = get_rotation(rotation_id)

        layer_ids = [
            layer.id
            for layer in (
                RotationLayer
                .select(RotationLayer.id)
                .where(RotationLayer.rotation == rotation)
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
                enabled=False,
                deleted=True,
                deleted_at=utc_now(),
            ).where(
                RotationLayer.id.in_(layer_ids)
            ).execute()

        # Legacy cleanup, если старая таблица rotation_member еще существует.
        RotationMember.delete().where(
            RotationMember.rotation == rotation
        ).execute()

        # Overrides принадлежат rotation, поэтому удаляем их.
        RotationOverride.delete().where(
            RotationOverride.rotation == rotation
        ).execute()

        # Чтобы alert routes не ссылались на удаленную rotation.
        AlertRoute.update(
            rotation=None,
        ).where(
            AlertRoute.rotation == rotation
        ).execute()

        rotation.enabled = False
        rotation.deleted = True
        rotation.deleted_at = utc_now()
        rotation.save()

        return rotation


def get_rotation_override(override_id):
    """
    Return a rotation override by id.
    """

    return RotationOverride.get_by_id(override_id)


def delete_rotation_override(override_id):
    """
    Delete a rotation override.
    """

    override = get_rotation_override(override_id)
    override.delete_instance()
    return True


def get_rotation_member(member_id):
    """
    Return a rotation member by id.
    """

    return RotationMember.get_by_id(member_id)


def update_rotation_member(member_id, position, active=True):
    """
    Update a rotation member.
    """

    member = get_rotation_member(member_id)
    member.position = position
    member.active = active
    member.save()
    return member


def delete_rotation_member(member_id: int) -> dict:
    """
    Permanently remove user from rotation.
    """
    member = get_rotation_member(member_id)

    data = {
        "id": member.id,
        "rotation_id": member.rotation.id,
        "team_id": member.rotation.team.id,
        "user_id": member.user.id,
    }

    member.delete_instance()

    return data


def list_rotation_team_users(rotation_id: int, active_only: bool = True):
    """
    Return users that belong to the team of the given rotation.

    Used by UI selects for adding rotation members and overrides.
    """
    rotation = get_rotation(rotation_id)

    query = (
        TeamUser
        .select()
        .where(TeamUser.team == rotation.team_id)
        .order_by(TeamUser.id.asc())
    )

    if active_only:
        query = query.where(TeamUser.active == True)

    return list(query)


def ensure_user_in_rotation_team(rotation_id: int, user_id: int):
    """
    Ensure that user is an active member of the rotation team.

    This protects API calls from manually adding users from another team.
    """
    rotation = get_rotation(rotation_id)

    membership = (
        TeamUser
        .select()
        .where(
            (TeamUser.team == rotation.team_id) &
            (TeamUser.user == user_id) &
            (TeamUser.active == True)
        )
        .first()
    )

    if not membership:
        raise ValueError("User is not an active member of the rotation team")

    return membership


def list_rotation_layers(rotation_id, enabled_only=False, include_deleted=False):
    """Return layers for a rotation ordered by priority.

    Higher priority wins. For same priority, newer layer wins.
    """

    query = RotationLayer.select().where(RotationLayer.rotation == rotation_id)

    if not include_deleted:
        query = query.where(RotationLayer.deleted == False)

    if enabled_only:
        query = query.where(RotationLayer.enabled == True)

    return list(query.order_by(RotationLayer.priority.desc(), RotationLayer.id.desc()))


def get_rotation_layer(layer_id, include_deleted=False):
    """Return a rotation layer by id."""

    query = RotationLayer.select().where(RotationLayer.id == layer_id)

    if not include_deleted:
        query = query.where(RotationLayer.deleted == False)

    return query.get()


def get_or_create_default_layer(rotation_id):
    """Return the default layer for a rotation, creating it from rotation settings."""

    rotation = get_rotation(rotation_id)

    layer = (
        RotationLayer.select()
        .where(
            (RotationLayer.rotation == rotation_id)
            & (RotationLayer.name == "Default layer")
            & (RotationLayer.deleted == False)
        )
        .first()
    )

    if layer:
        return layer

    return RotationLayer.create(
        rotation=rotation,
        name="Default layer",
        description="Default layer created from rotation settings",
        priority=0,
        start_at=rotation.start_at,
        duration_seconds=rotation.duration_seconds,
        rotation_type=rotation.rotation_type,
        interval_value=rotation.interval_value,
        interval_unit=rotation.interval_unit,
        handoff_time=rotation.handoff_time,
        handoff_weekday=rotation.handoff_weekday,
        timezone=rotation.timezone,
        enabled=rotation.enabled,
    )


def create_rotation_layer(
    rotation_id,
    name,
    description=None,
    priority=0,
    start_at=None,
    duration_seconds=None,
    rotation_type=None,
    interval_value=None,
    interval_unit=None,
    handoff_time=None,
    handoff_weekday=None,
    timezone=None,
    enabled=True,
):
    """Create a layer inside a rotation."""

    rotation = get_rotation(rotation_id)

    return RotationLayer.create(
        rotation=rotation,
        name=name,
        description=description,
        priority=priority,
        start_at=start_at or rotation.start_at,
        duration_seconds=duration_seconds or rotation.duration_seconds,
        rotation_type=rotation_type or rotation.rotation_type,
        interval_value=interval_value or rotation.interval_value,
        interval_unit=interval_unit or rotation.interval_unit,
        handoff_time=handoff_time or rotation.handoff_time,
        handoff_weekday=handoff_weekday if handoff_weekday is not None else rotation.handoff_weekday,
        timezone=timezone or rotation.timezone,
        enabled=enabled,
    )


def update_rotation_layer(layer_id, data):
    """Update a rotation layer."""

    layer = get_rotation_layer(layer_id)

    for field in [
        "name",
        "description",
        "priority",
        "start_at",
        "duration_seconds",
        "rotation_type",
        "interval_value",
        "interval_unit",
        "handoff_time",
        "handoff_weekday",
        "timezone",
        "enabled",
    ]:
        if field in data:
            setattr(layer, field, data[field])

    layer.save()
    return layer


def soft_delete_rotation_layer(layer_id):
    """Soft-delete a rotation layer."""

    layer = get_rotation_layer(layer_id)
    layer.enabled = False
    layer.deleted = True
    layer.deleted_at = utc_now()
    layer.save()
    return layer


def _rotation_layer_member_effective_at(model, at):
    return (
        ((model.starts_at.is_null(True)) | (model.starts_at <= at))
        & ((model.ends_at.is_null(True)) | (model.ends_at > at))
    )


def list_rotation_layer_members(
    layer_id,
    active_only=False,
    at=None,
    include_inactive_users=False,
):
    """Return current/effective members of a rotation layer."""

    query = RotationLayerMember.select().where(
        RotationLayerMember.layer == layer_id
    )

    if at is not None:
        query = query.where(
            _rotation_layer_member_effective_at(RotationLayerMember, at)
        )

    if active_only:
        query = query.where(RotationLayerMember.active == True)
        if at is None:
            query = query.where(RotationLayerMember.ends_at.is_null(True))

    if not include_inactive_users:
        query = (
            query
            .join(User)
            .where(
                (User.active == True)
                & (User.deleted == False)
            )
        )

    return list(
        query.order_by(
            RotationLayerMember.position.asc(),
            RotationLayerMember.id.asc(),
        )
    )


def list_rotation_layer_member_periods(
    layer_id,
    start_at=None,
    end_at=None,
    include_inactive_users=True,
):
    """Return membership periods overlapping the requested range."""

    query = RotationLayerMember.select().where(
        RotationLayerMember.layer == layer_id
    )

    if start_at is not None:
        query = query.where(
            (RotationLayerMember.ends_at.is_null(True))
            | (RotationLayerMember.ends_at > start_at)
        )

    if end_at is not None:
        query = query.where(
            (RotationLayerMember.starts_at.is_null(True))
            | (RotationLayerMember.starts_at < end_at)
        )

    if not include_inactive_users:
        query = (
            query
            .join(User)
            .where(
                (User.active == True)
                & (User.deleted == False)
            )
        )

    return list(
        query.order_by(
            RotationLayerMember.position.asc(),
            RotationLayerMember.id.asc(),
        )
    )


def add_rotation_layer_member(layer_id, user_id, position, starts_at=None):
    """Add user to layer as a new membership period."""

    starts_at = starts_at or utc_now()

    with database_proxy.atomic():
        (
            RotationLayerMember
            .update(
                active=False,
                ends_at=starts_at,
            )
            .where(
                (RotationLayerMember.layer == layer_id)
                & (RotationLayerMember.user == user_id)
                & (RotationLayerMember.ends_at.is_null(True))
            )
            .execute()
        )

        position_conflict = (
            RotationLayerMember
            .select()
            .where(
                (RotationLayerMember.layer == layer_id)
                & (RotationLayerMember.position == position)
                & (RotationLayerMember.active == True)
                & _rotation_layer_member_effective_at(
                    RotationLayerMember,
                    starts_at,
                )
            )
            .first()
        )

        if position_conflict:
            raise ValueError("rotation layer position is already occupied")

        return RotationLayerMember.create(
            layer=layer_id,
            user=user_id,
            position=position,
            active=True,
            starts_at=starts_at,
            ends_at=None,
        )


def get_rotation_layer_member(member_id):
    """Return one layer member."""

    return RotationLayerMember.get_by_id(member_id)


def update_rotation_layer_member(member_id, position, active=True):
    """Update layer member without rewriting historical schedule."""

    member = get_rotation_layer_member(member_id)
    now = utc_now()

    if not active:
        member.active = False
        if member.ends_at is None:
            member.ends_at = now
        member.save()
        return member

    if member.ends_at is not None or not member.active:
        return add_rotation_layer_member(
            layer_id=member.layer.id,
            user_id=member.user.id,
            position=position,
            starts_at=now,
        )

    if position != member.position:
        member.active = False
        member.ends_at = now
        member.save()

        return add_rotation_layer_member(
            layer_id=member.layer.id,
            user_id=member.user.id,
            position=position,
            starts_at=now,
        )

    return member


def delete_rotation_layer_member(member_id):
    """Close member period instead of deleting it."""

    member = get_rotation_layer_member(member_id)

    data = {
        "id": member.id,
        "layer_id": member.layer.id,
        "rotation_id": member.layer.rotation.id,
        "team_id": member.layer.rotation.team.id,
        "user_id": member.user.id,
    }

    member.active = False
    if member.ends_at is None:
        member.ends_at = utc_now()
    member.save()

    return data


def list_rotation_layer_restrictions(layer_id):
    """Return restrictions for a layer."""

    return list(
        RotationLayerRestriction.select()
        .where(RotationLayerRestriction.layer == layer_id)
        .order_by(
            RotationLayerRestriction.weekday.asc(nulls="FIRST"),
            RotationLayerRestriction.start_time.asc(),
            RotationLayerRestriction.id.asc(),
        )
    )


def replace_rotation_layer_restrictions(layer_id, restrictions):
    """Replace all restrictions for a layer."""

    RotationLayerRestriction.delete().where(
        RotationLayerRestriction.layer == layer_id
    ).execute()

    result = []
    for item in restrictions:
        result.append(
            RotationLayerRestriction.create(
                layer=layer_id,
                weekday=item.get("weekday"),
                start_time=item["start_time"],
                end_time=item["end_time"],
            )
        )

    return result


def set_rotation_enabled(rotation_id: int, enabled: bool):
    """Enable or disable a rotation without deleting schedule data."""
    rotation = get_rotation(rotation_id)
    rotation.enabled = enabled
    rotation.save()
    return rotation


def list_rotations_for_health(rotation_ids, active_only=True):
    """Return rotations with layers, layer members and users prefetched.

    Used by the on-call health summaries endpoint to avoid N+1 queries.
    This is intentionally separate from list_rotations(), because most
    rotation list callers do not need layers and members loaded.
    """
    if not rotation_ids:
        return []

    query = (
        Rotation
        .select(Rotation)
        .join(Team, on=(Rotation.team == Team.id))
        .switch(Rotation)
        .where(
            (Rotation.id.in_(rotation_ids)) &
            (Rotation.deleted == False)
        )
        .order_by(Rotation.id.asc())
    )

    if active_only:
        query = query.where(
            (Team.active == True) &
            (Team.deleted == False)
        )
        query = (
            query
            .join(Group, on=(Team.group == Group.id))
            .where(
                (Group.active == True) &
                (Group.deleted == False)
            )
            .switch(Rotation)
        )

    layers_query = (
        RotationLayer
        .select(RotationLayer)
        .where(RotationLayer.deleted == False)
        .order_by(
            RotationLayer.rotation.asc(),
            RotationLayer.priority.desc(),
            RotationLayer.id.desc(),
        )
    )

    members_query = (
        RotationLayerMember
        .select(RotationLayerMember)
        .order_by(
            RotationLayerMember.layer.asc(),
            RotationLayerMember.position.asc(),
            RotationLayerMember.id.asc(),
        )
    )

    users_query = User.select(User)

    return list(prefetch(
        query,
        layers_query,
        members_query,
        users_query,
    ))
