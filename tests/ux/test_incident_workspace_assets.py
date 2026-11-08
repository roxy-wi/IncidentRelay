"""Workspace localization and navigation regressions without browser setup."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_workspace_locales_and_template_labels():
    english = json.loads((ROOT / "app/static/i18n/en/incidents.json").read_text(encoding="utf-8"))
    for locale in ("ru", "de", "fr", "es", "zh"):
        translated = json.loads((ROOT / f"app/static/i18n/{locale}/incidents.json").read_text(encoding="utf-8"))
        assert translated.keys() == english.keys()
        for key, value in english.items():
            assert translated[key].strip(), (locale, key)
            assert re.findall(r"\{\w+\}", value) == re.findall(r"\{\w+\}", translated[key]), (locale, key)
    template = (ROOT / "app/templates/pages/incidents.html").read_text(encoding="utf-8")
    keys = re.findall(r"_\('(incidents\.[^']+)'\)", template)
    assert set(keys) <= english.keys()


def test_workspace_ids_do_not_collide_with_other_templates():
    workspace = ROOT / "app/templates/pages/incidents.html"
    ids = re.findall(r'id="([^"]+)"', workspace.read_text(encoding="utf-8"))
    assert len(ids) == len(set(ids))
    for template in (ROOT / "app/templates").rglob("*.html"):
        if template == workspace:
            continue
        other = re.findall(r'id="([^"]+)"', template.read_text(encoding="utf-8"))
        assert not set(ids).intersection(other), str(template)


def test_workspace_navigation_and_conflict_javascript():
    if not shutil.which("node"):
        pytest.skip("Node.js is required for JavaScript regression tests")
    result = subprocess.run(
        ["node", "tests/ux/incident_workspace_state.test.js"], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
