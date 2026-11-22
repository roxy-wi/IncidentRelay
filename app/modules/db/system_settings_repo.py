"""Persistence access to installation-wide settings."""

from app.modules.db.models import SystemSettings


def get_settings() -> SystemSettings:
    """Read the singleton afresh so each operation observes committed settings."""
    return SystemSettings.get_by_id(1)
