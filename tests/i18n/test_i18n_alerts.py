from pathlib import Path
import json
import re

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


def test_alert_templates_reference_existing_keys():
    messages = load_catalog("en")
    paths = [
        ROOT / "app" / "templates" / "pages" / "alerts.html",
        ROOT / "app" / "templates" / "pages" / "include" / "alerts_summary_grid.html",
    ]

    keys = set()
    for path in paths:
        content = path.read_text(encoding="utf-8")
        keys.update(re.findall(r"_\(['\"]([^'\"]+)['\"]\)", content))

    missing = sorted(key for key in keys if key not in messages)
    assert missing == []


def test_alert_javascript_references_existing_keys():
    messages = load_catalog("en")
    content = (
        ROOT / "app" / "static" / "js" / "pages" / "alerts.js"
    ).read_text(encoding="utf-8")

    keys = set(re.findall(r'i18n\.t\([""]([^""]+)[""]', content))
    missing = sorted(
        key
        for key in keys
        if key.startswith("alerts.") and key not in messages
    )
    assert missing == []
