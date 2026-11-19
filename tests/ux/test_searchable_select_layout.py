"""Check searchable controls against the production styles and Tom Select code."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests"
)
def test_searchable_select_layout():
    result = subprocess.run(
        [shutil.which("node") or "node", "tests/ux/searchable_select_layout.browser.js"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
