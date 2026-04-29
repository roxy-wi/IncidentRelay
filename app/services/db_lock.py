import socket
import uuid

from app.settings import Config
from app.modules.db import locks_repo


def make_owner():
    """
    Create a unique lock owner id.
    """

    return f"{socket.gethostname()}:{uuid.uuid4()}"


def acquire_db_lock(name, ttl_seconds=None):
    """
    Acquire a database-backed lock.
    """

    ttl_seconds = ttl_seconds or Config.SCHEDULER_LOCK_TTL_SECONDS
    owner = make_owner()
    if locks_repo.acquire_lock(name, owner, ttl_seconds):
        return owner
    return None


def release_db_lock(name, owner):
    """
    Release a database-backed lock.
    """

    if owner:
        locks_repo.release_lock(name, owner)
