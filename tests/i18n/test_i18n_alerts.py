from pathlib import Path
import json
import re

import pytest

from app.i18n import SUPPORTED_LOCALES


ROOT = Path(__file__).resolve().parents[2]


def load_catalog(locale):
    messages = {}
    directory = ROOT / "app" / "static" / "i18n" / locale

    for path in sorted(directory.glob("*.json")):
        messages.update(json.loads(path.read_text(encoding="utf-8")))

    return messages


def test_alert_catalogs_have_matching_keys():
    english_keys = set(load_catalog("en"))

    for locale in SUPPORTED_LOCALES:
        assert english_keys == set(load_catalog(locale)), locale


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_analytics_catalogs_have_matching_keys_and_placeholders(locale):
    """Require complete analytics translations without relying on English fallback."""
    catalog_root = ROOT / "app" / "static" / "i18n"
    english = json.loads(
        (catalog_root / "en" / "alert_analytics.json").read_text(encoding="utf-8")
    )
    translated = json.loads(
        (catalog_root / locale / "alert_analytics.json").read_text(encoding="utf-8")
    )

    assert translated.keys() == english.keys()
    for key, value in english.items():
        assert isinstance(translated[key], str) and translated[key].strip(), key
        assert sorted(re.findall(r"\{[A-Za-z0-9_]+\}", translated[key])) == sorted(
            re.findall(r"\{[A-Za-z0-9_]+\}", value)
        ), key


def test_alert_templates_reference_existing_keys():
    messages = load_catalog("en")
    paths = [
        ROOT / "app" / "templates" / "pages" / "alerts.html",
        ROOT / "app" / "templates" / "pages" / "dashboard.html",
        ROOT / "app" / "templates" / "pages" / "include" / "alert_involvement_options.html",
        ROOT / "app" / "templates" / "pages" / "include" / "alerts_summary_grid.html",
        ROOT / "app" / "templates" / "pages" / "include" / "alert_analytics_panel.html",
    ]

    keys = set()
    for path in paths:
        content = path.read_text(encoding="utf-8")
        keys.update(re.findall(r"_\(['\"]([^'\"]+)['\"]\)", content))

    missing = sorted(key for key in keys if key not in messages)
    assert missing == []


def test_alert_javascript_references_existing_keys():
    messages = load_catalog("en")
    paths = [
        ROOT / "app" / "static" / "js" / "pages" / "alerts.js",
        ROOT / "app" / "static" / "js" / "pages" / "dashboard.js",
        ROOT / "app" / "static" / "js" / "pages" / "alert_analytics.js",
    ]
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in paths
    )

    # Check complete literal keys, not prefixes of dynamically composed keys.
    keys = set(re.findall(r"""i18n\.t\(\s*["']([^"']+)["']\s*(?=[,)])""", content))
    missing = sorted(
        key
        for key in keys
        if key.startswith(("alerts.", "overview.")) and key not in messages
    )
    assert missing == []
