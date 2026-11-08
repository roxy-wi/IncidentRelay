"""Check the shared browser color rule and contrast against backend vectors."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.modules.user_colors import default_user_color


def test_browser_color_rule_and_text_contrast():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for JavaScript tests")
    vectors = [
        [value, default_user_color(value)]
        for value in (1, 2, 20, 256, 4096, 16777215, 2147483647)
    ]
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "tests/ux/user_appearance.test.js"],
        cwd=root,
        env={**os.environ, "USER_COLOR_VECTORS": json.dumps(vectors)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
