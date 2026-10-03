from datetime import timedelta

from peewee import IntegrityError

from app.modules.db.models import AppLock
from app.modules.common import utc_now


def acquire_lock(name, owner, ttl_seconds):
    """
    Acquire a database-backed lock.
    """

    now = utc_now()
    expires_at = now + timedelta(seconds=ttl_seconds)

    try:
        AppLock.create(name=name, owner=owner, expires_at=expires_at, updated_at=now)
        return True
    except IntegrityError:
        pass

    lock = AppLock.get_or_none(AppLock.name == name)
    if not lock or lock.expires_at > now:
        return False

    updated_rows = (
        AppLock.update(owner=owner, expires_at=expires_at, updated_at=now)
        .where((AppLock.name == name) & (AppLock.expires_at <= now))
        .execute()
    )
    return bool(updated_rows)


def release_lock(name, owner):
    """
    Release a database-backed lock.
    """

    return AppLock.delete().where((AppLock.name == name) & (AppLock.owner == owner)).execute()


def touch_lock(name, owner, ttl_seconds):
    """
    Create or refresh a long-lived lock row without releasing it.

    Unlike acquire/release, the row stays in place and only its
    timestamps move, so other processes can read how recently the owner
    ran. The scheduler uses this as its heartbeat.
    """

    now = utc_now()
    expires_at = now + timedelta(seconds=ttl_seconds)

    updated = (
        AppLock.update(owner=owner, expires_at=expires_at, updated_at=now)
        .where(AppLock.name == name)
        .execute()
    )

    if updated:
        return

    try:
        AppLock.create(name=name, owner=owner, expires_at=expires_at, updated_at=now)
    except IntegrityError:
        # Another writer created it first — its timestamp is fresh too.
        pass
