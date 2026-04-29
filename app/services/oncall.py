from datetime import datetime

from app.modules.db import rotations_repo


def get_current_oncall_user(rotation, now=None):
    """
    Return the current on-call user for a rotation.
    """

    if not rotation:
        return None

    now = now or datetime.utcnow()
    override = rotations_repo.get_active_override(rotation.id, now)
    if override:
        return override.user

    members = rotations_repo.list_rotation_members(rotation.id)
    if not members:
        return None

    elapsed = int((now - rotation.start_at).total_seconds())
    if elapsed < 0:
        return members[0].user

    slot = elapsed // rotation.duration_seconds
    return members[slot % len(members)].user


def get_next_rotation_user(rotation, current_user=None):
    """
    Return the next rotation user after the current user.
    """

    members = rotations_repo.list_rotation_members(rotation.id)
    if not members:
        return None
    if not current_user:
        return members[0].user
    for index, member in enumerate(members):
        if member.user.id == current_user.id:
            return members[(index + 1) % len(members)].user
    return members[0].user
