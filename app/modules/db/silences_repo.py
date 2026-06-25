from datetime import datetime, timedelta

from app.modules.db.models import Group, Silence, Team


def list_silences(
    team_id=None,
    team_ids=None,
    active_only=True,
    include_deleted=False,
    include_expired_history=False,
    expired_retention_days=30,
    now=None,
):
    """Return silence rules."""
    query = (
        Silence
        .select(Silence)
        .join(Team, on=(Silence.team == Team.id))
        .switch(Silence)
        .order_by(Silence.id.desc())
    )

    if not include_deleted:
        query = query.where(Silence.deleted == False)

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
            .switch(Silence)
        )

    if not include_expired_history:
        cutoff = (now or datetime.utcnow()) - timedelta(days=expired_retention_days)
        query = query.where(Silence.ends_at >= cutoff)

    if team_id:
        query = query.where(Silence.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return []
        query = query.where(Silence.team.in_(team_ids))

    return list(query)


def list_active_silences(team_id, now=None):
    """
    Return active silences for a team.
    """

    now = now or datetime.utcnow()
    return list(
        Silence.select()
        .where(
            (Silence.team == team_id)
            & (Silence.enabled == True)
            & (Silence.deleted == False)
            & (Silence.starts_at <= now)
            & (Silence.ends_at > now)
        )
        .order_by(Silence.id.desc())
    )


def create_silence(
    team_id,
    name,
    starts_at,
    ends_at,
    reason=None,
    matcher_preset_id=None,
    matchers=None,
    created_by=None,
):
    """Create a silence rule."""
    return Silence.create(
        team=team_id,
        name=name,
        reason=reason,
        matcher_preset=matcher_preset_id,
        matchers=matchers or {},
        starts_at=starts_at,
        ends_at=ends_at,
        created_by=created_by,
    )


def get_silence(silence_id, include_deleted=False):
    """
    Return a silence by id.
    """

    query = Silence.select().where(Silence.id == silence_id)

    if not include_deleted:
        query = query.where(Silence.deleted == False)

    return query.get()


def update_silence(silence_id, data):
    """
    Update a silence rule.
    """

    silence = get_silence(silence_id)
    for field in ["team", "name", "reason", "matcher_preset", "matchers", "starts_at", "ends_at", "created_by", "enabled"]:
        if field in data:
            setattr(silence, field, data[field])
    silence.save()
    return silence


def disable_silence(silence_id):
    """Disable a silence rule."""
    silence = get_silence(silence_id)
    silence.enabled = False
    silence.save()
    return silence


def soft_delete_silence(silence_id):
    """
    Soft-delete a silence rule.
    """

    silence = get_silence(silence_id)
    silence.enabled = False
    silence.deleted = True
    silence.deleted_at = datetime.utcnow()
    silence.save()
    return silence
