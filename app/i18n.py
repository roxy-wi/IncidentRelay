"""Interface localization shared by Jinja templates and browser JavaScript."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app, request


DEFAULT_LOCALE = "en"
LOCALE_COOKIE_NAME = "incidentrelay_locale"
SUPPORTED_LOCALES = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "ru": "Русский",
    "zh": "简体中文",
}


def normalize_locale(value: str | None) -> str | None:
    """Normalize a browser/user locale and reject unsupported values."""
    if not value:
        return None

    normalized = str(value).strip().lower().replace("_", "-")
    if normalized in SUPPORTED_LOCALES:
        return normalized

    language = normalized.split("-", 1)[0]
    if language in SUPPORTED_LOCALES:
        return language

    return None


def get_current_locale() -> str:
    """Resolve locale from user preference, cookie, browser, then fallback."""
    user = getattr(request, "current_user", None)
    user_locale = normalize_locale(getattr(user, "locale", None))
    if user_locale:
        return user_locale

    cookie_locale = normalize_locale(request.cookies.get(LOCALE_COOKIE_NAME))
    if cookie_locale:
        return cookie_locale

    browser_locale = request.accept_languages.best_match(
        tuple(SUPPORTED_LOCALES.keys())
    )
    return normalize_locale(browser_locale) or DEFAULT_LOCALE


@lru_cache(maxsize=32)
def _load_catalog(static_folder: str, locale: str) -> dict[str, str]:
    safe_locale = normalize_locale(locale)
    messages: dict[str, str] = {}

    if not safe_locale:
        return messages

    directory = Path(static_folder) / "i18n" / safe_locale

    if not directory.is_dir():
        return messages

    for path in sorted(directory.glob("*.json")):
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(payload, dict):
            continue

        messages.update(
            {
                str(key): value
                for key, value in payload.items()
                if isinstance(value, str)
            }
        )

    return messages

def get_messages(locale: str | None = None) -> dict[str, str]:
    """Return selected messages merged over the English fallback catalog."""
    selected_locale = normalize_locale(locale) or get_current_locale()
    static_folder = current_app.static_folder

    if not static_folder:
        return {}

    messages = dict(_load_catalog(static_folder, DEFAULT_LOCALE))
    if selected_locale != DEFAULT_LOCALE:
        messages.update(_load_catalog(static_folder, selected_locale))

    return messages


def translate(key: str, **params: object) -> str:
    """Translate a key for Jinja templates with safe fallback to the key."""
    template = get_messages().get(key, key)

    if not params:
        return template

    try:
        return template.format(**params)
    except (KeyError, ValueError):
        return template


def register_i18n(app) -> None:
    """Expose localization helpers and catalogs to every Jinja template."""

    @app.context_processor
    def inject_i18n_context():
        locale = get_current_locale()
        return {
            "_": translate,
            "current_locale": locale,
            "supported_locales": SUPPORTED_LOCALES,
            "i18n_messages": get_messages(locale),
        }
