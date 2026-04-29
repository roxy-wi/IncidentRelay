from datetime import datetime, timedelta

from peewee import IntegrityError

from app.modules.db.models import AppLock


def acquire_lock(name, owner, ttl_seconds):
    """
    Acquire a database-backed lock.
    """

    now = datetime.utcnow()
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
