"""User interface preference helpers."""

from __future__ import annotations

from flask import request


DEFAULT_THEME = "system"
SUPPORTED_THEMES = ("system", "light", "dark")


def normalize_theme(value: str | None) -> str | None:
    """Normalize a theme preference and reject unsupported values."""
    if value is None:
        return None

    normalized = str(value).strip().lower()
    if normalized in SUPPORTED_THEMES:
        return normalized

    return None


def get_current_theme() -> str:
    """Return the authenticated user's theme preference or system default."""
    user = getattr(request, "current_user", None)
    return normalize_theme(getattr(user, "theme", None)) or DEFAULT_THEME
