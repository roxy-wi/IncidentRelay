from datetime import datetime

from app.modules.db.models import Rotation, RotationMember, RotationOverride


def list_rotations(team_id=None, team_ids=None, enabled_only=False, include_deleted=False):
    """
    Return rotations.
    """

    query = Rotation.select().order_by(Rotation.id.asc())

    if not include_deleted:
        query = query.where(Rotation.deleted == False)

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


def create_rotation(team_id, name, description, start_at, duration_seconds, reminder_interval_seconds=300, rotation_type="daily", interval_value=1, interval_unit="days", handoff_time="09:00", handoff_weekday=None, timezone="UTC"):
    """
    Create a rotation.
    """

    return Rotation.create(
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
    )


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


def list_rotation_members(rotation_id):
    """
    Return active rotation members ordered by position.
    """

    return list(
        RotationMember.select()
        .where((RotationMember.rotation == rotation_id) & (RotationMember.active == True))
        .order_by(RotationMember.position.asc(), RotationMember.id.asc())
    )


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


def list_rotation_overrides(rotation_id, start_at=None, end_at=None):
    """
    Return overrides for a rotation.
    """

    query = RotationOverride.select().where(RotationOverride.rotation == rotation_id)
    if start_at and end_at:
        query = query.where((RotationOverride.starts_at < end_at) & (RotationOverride.ends_at > start_at))
    return list(query.order_by(RotationOverride.id.asc()))


def get_active_override(rotation_id, now=None):
    """
    Return the active override for a rotation.
    """

    now = now or datetime.utcnow()
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


def disable_rotation(rotation_id):
    """
    Soft-delete a rotation.
    """

    return soft_delete_rotation(rotation_id)


def soft_delete_rotation(rotation_id):
    """
    Soft-delete a rotation.
    """

    rotation = get_rotation(rotation_id)
    rotation.enabled = False
    rotation.deleted = True
    rotation.deleted_at = datetime.utcnow()
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


def disable_rotation_member(member_id):
    """
    Disable a rotation member.
    """

    member = get_rotation_member(member_id)
    member.active = False
    member.save()
    return member
