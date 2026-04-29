from datetime import datetime

from app.models import Silence


def list_silences(team_id=None, team_ids=None, include_deleted=False):
    """
    Return silence rules.
    """

    query = Silence.select().order_by(Silence.id.desc())

    if not include_deleted:
        query = query.where(Silence.deleted == False)

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


def create_silence(team_id, name, starts_at, ends_at, reason=None, matchers=None, created_by=None):
    """
    Create a silence rule.
    """

    return Silence.create(
        team=team_id,
        name=name,
        reason=reason,
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
    for field in ["team", "name", "reason", "matchers", "starts_at", "ends_at", "created_by", "enabled"]:
        if field in data:
            setattr(silence, field, data[field])
    silence.save()
    return silence


def disable_silence(silence_id):
    """
    Soft-delete a silence rule.
    """

    return soft_delete_silence(silence_id)


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
