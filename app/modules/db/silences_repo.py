from datetime import datetime, timedelta

from app.modules.db.models import (
    Alert,
    Group,
    Silence,
    SilenceAlertApplication,
    Team,
)
from app.modules.common import utc_now


def list_silences(
    team_id: int | None = None,
    team_ids: list[int] | None = None,
    active_only: bool = True,
    include_deleted: bool = False,
    include_expired_history: bool = False,
    expired_retention_days: int = 30,
    now: datetime | None = None,
) -> list[Silence]:
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
        cutoff = (now or utc_now()) - timedelta(days=expired_retention_days)
        query = query.where(Silence.ends_at >= cutoff)

    if team_id:
        query = query.where(Silence.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return []
        query = query.where(Silence.team.in_(team_ids))

    return list(query)


def list_active_silences(
    team_id: int,
    now: datetime | None = None,
) -> list[Silence]:
    """Return active silences for a team."""
    now = now or utc_now()
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


def list_due_retroactive_silences(
    now: datetime | None = None,
) -> list[Silence]:
    """Return active retroactive silences that still require reconciliation."""
    now = now or utc_now()
    return list(
        Silence.select()
        .where(
            (Silence.enabled == True)
            & (Silence.deleted == False)
            & (Silence.apply_to_existing == True)
            & (Silence.starts_at <= now)
            & (Silence.ends_at > now)
            & (Silence.reconciled_at.is_null(True))
        )
        .order_by(Silence.starts_at.asc(), Silence.id.asc())
    )


def list_silences_with_due_releases(
    now: datetime | None = None,
) -> list[Silence]:
    """Return silences with active applications that are no longer active."""
    now = now or utc_now()
    return list(
        Silence.select(Silence)
        .join(SilenceAlertApplication)
        .where(
            (SilenceAlertApplication.active == True)
            & (Silence.reactivate_on_end == True)
            & (
                (Silence.enabled == False)
                | (Silence.deleted == True)
                | (Silence.ends_at <= now)
            )
        )
        .distinct()
        .order_by(Silence.id.asc())
    )


def create_silence(
    team_id: int,
    name: str,
    starts_at: datetime,
    ends_at: datetime,
    reason: str | None = None,
    matcher_preset_id: int | None = None,
    matchers: dict | None = None,
    created_by: int | None = None,
    apply_to_existing: bool = False,
    reactivate_on_end: bool = True,
) -> Silence:
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
        apply_to_existing=apply_to_existing,
        reactivate_on_end=reactivate_on_end,
        reconciled_at=None,
        updated_at=utc_now(),
    )


def get_silence(
    silence_id: int,
    include_deleted: bool = False,
) -> Silence:
    """Return a silence by id."""
    query = Silence.select().where(Silence.id == silence_id)

    if not include_deleted:
        query = query.where(Silence.deleted == False)

    return query.get()


def update_silence(silence_id: int, data: dict) -> Silence:
    """Update a silence rule and request lifecycle reconciliation."""
    silence = get_silence(silence_id)
    for field in [
        "team",
        "name",
        "reason",
        "matcher_preset",
        "matchers",
        "starts_at",
        "ends_at",
        "created_by",
        "enabled",
        "apply_to_existing",
        "reactivate_on_end",
    ]:
        if field in data:
            setattr(silence, field, data[field])
    silence.reconciled_at = None
    silence.updated_at = utc_now()
    silence.save()
    return silence


def enable_silence(silence_id: int) -> Silence:
    """Enable a silence rule and request lifecycle reconciliation."""
    silence = get_silence(silence_id)
    silence.enabled = True
    silence.reconciled_at = None
    silence.updated_at = utc_now()
    silence.save()
    return silence


def disable_silence(silence_id: int) -> Silence:
    """Disable a silence rule."""
    silence = get_silence(silence_id)
    silence.enabled = False
    silence.reconciled_at = None
    silence.updated_at = utc_now()
    silence.save()
    return silence


def soft_delete_silence(silence_id: int) -> Silence:
    """Soft-delete a silence rule."""
    silence = get_silence(silence_id)
    silence.enabled = False
    silence.deleted = True
    silence.deleted_at = utc_now()
    silence.reconciled_at = None
    silence.updated_at = utc_now()
    silence.save()
    return silence


def get_or_create_application(
    *,
    silence: Silence,
    alert: Alert,
    previous_status: str,
    source: str,
    now: datetime | None = None,
) -> tuple[SilenceAlertApplication, bool]:
    """Create or reactivate the persisted Silence-to-alert relation."""
    now = now or utc_now()
    application, created = SilenceAlertApplication.get_or_create(
        silence=silence.id,
        alert=alert.id,
        defaults={
            "group": alert.group_id,
            "previous_status": previous_status,
            "source": source,
            "active": True,
            "applied_at": now,
        },
    )

    if not created and not application.active:
        application.group = alert.group_id
        application.previous_status = previous_status
        application.source = source
        application.active = True
        application.applied_at = now
        application.released_at = None
        application.release_reason = None
        application.save()
        created = True

    return application, created


def list_active_applications_for_silence(
    silence_id: int,
) -> list[SilenceAlertApplication]:
    """Return active applications belonging to one Silence."""
    return list(
        SilenceAlertApplication.select()
        .where(
            (SilenceAlertApplication.silence == silence_id)
            & (SilenceAlertApplication.active == True)
        )
        .order_by(SilenceAlertApplication.id.asc())
    )


def has_other_active_application(
    alert_id: int,
    *,
    exclude_application_id: int | None = None,
) -> bool:
    """Return whether another active Silence application covers an alert."""
    query = SilenceAlertApplication.select().where(
        (SilenceAlertApplication.alert == alert_id)
        & (SilenceAlertApplication.active == True)
    )
    if exclude_application_id is not None:
        query = query.where(SilenceAlertApplication.id != exclude_application_id)
    return query.exists()


def release_application(
    application: SilenceAlertApplication,
    *,
    reason: str,
    now: datetime | None = None,
) -> SilenceAlertApplication:
    """Mark a Silence application as released."""
    application.active = False
    application.released_at = now or utc_now()
    application.release_reason = reason
    application.save()
    return application
