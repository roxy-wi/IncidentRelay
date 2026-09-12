"""Database helpers for temporary AlertGroup shelving."""

from app.modules.common import utc_now
from app.modules.db.models import AlertGroupShelve


def get_current_shelve(group_id, *, now=None):
    """Return the effective active shelf for one group, if any."""
    now = now or utc_now()
    return (
        AlertGroupShelve.select()
        .where(
            (AlertGroupShelve.alert_group == int(group_id))
            & (AlertGroupShelve.active == True)  # noqa: E712
            & (
                AlertGroupShelve.ends_at.is_null(True)
                | (AlertGroupShelve.ends_at > now)
            )
        )
        .order_by(AlertGroupShelve.shelved_at.desc(), AlertGroupShelve.id.desc())
        .first()
    )


def get_active_record(group_id):
    """Return the persisted active shelf, including one that is already due."""
    return (
        AlertGroupShelve.select()
        .where(
            (AlertGroupShelve.alert_group == int(group_id))
            & (AlertGroupShelve.active == True)  # noqa: E712
        )
        .order_by(AlertGroupShelve.shelved_at.desc(), AlertGroupShelve.id.desc())
        .first()
    )


def list_due_shelves(*, now=None, limit=100):
    """Return active shelves whose explicit expiry is due."""
    now = now or utc_now()
    return list(
        AlertGroupShelve.select()
        .where(
            (AlertGroupShelve.active == True)  # noqa: E712
            & AlertGroupShelve.ends_at.is_null(False)
            & (AlertGroupShelve.ends_at <= now)
        )
        .order_by(AlertGroupShelve.ends_at.asc(), AlertGroupShelve.id.asc())
        .limit(max(1, int(limit or 100)))
    )
