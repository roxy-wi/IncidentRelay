"""Run strict membership/resource identity contracts under pytest."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_membership_ids_are_not_accepted_as_resource_group_ids():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [node, str(root / "tests/ux/strict_group_membership_identity.test.js")],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
