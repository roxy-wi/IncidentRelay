"""Smoke tests for the 2.4 UI without a browser-only dependency."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LOCALES = ("en", "ru", "de", "fr", "es", "zh")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def test_reopen_ui_translation_parity():
    for filename in ("alert_details.json", "incidents.json"):
        english = json.loads((ROOT / "app/static/i18n/en" / filename).read_text(encoding="utf-8"))
        keys = [
            key for key in english
            if key.startswith(("alert_details.explain.reopen", "alert_details.events.view_child",
                               "alert_details.children.reopened", "alert_details.recovery.technical_resolved",
                               "incidents.activity.reopened", "incidents.activity.open_reopened"))
        ]
        assert keys
        for locale in LOCALES:
            current = json.loads((ROOT / "app/static/i18n" / locale / filename).read_text(encoding="utf-8"))
            for key in keys:
                assert key in current, (locale, key)
                assert sorted(PLACEHOLDER.findall(current[key])) == sorted(
                    PLACEHOLDER.findall(english[key])
                ), (locale, key)


def test_javascript_summary_and_child_navigation():
    if not shutil.which("node"):
        pytest.skip("Node.js is required for runtime UX contracts")
    subprocess.run(
        ["node", str(ROOT / "tests/ux/incident_summary_and_reopen.test.js")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
