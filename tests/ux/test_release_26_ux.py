"""Regression coverage for paginated on-call pages in release 2.6."""

import json
import os
import shutil
import subprocess
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.common import utc_now
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_team,
    create_user,
)

ROOT = Path(__file__).resolve().parents[2]


def test_client_table_pagination():
    """Exercise boundaries, page sizes, filtering and a shrinking collection."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    subprocess.run(
        [node, "tests/ux/table_pagination.test.js"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )


def test_member_view_translation_parity():
    """All supported locales explain read-only viewing and request failures."""
    for locale in ("en", "ru", "de", "fr", "es", "zh"):
        data = json.loads((ROOT / f"app/static/i18n/{locale}/teams.json").read_text(encoding="utf-8"))
        for key in ("teams.members.read_only", "teams.members.load_failed", "teams.permissions.view_members"):
            assert data[key].strip(), (locale, key)


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable browser tests and install Node playwright",
)
def test_oncall_pagination_browser(app, db):
    """Use actual API data to check pagination and health indicator alignment."""
    group = create_group()
    admin = create_user(group=group, group_role="user_admin")
    for index in range(27):
        team = create_team(group, name=f"Roster {index:02d}")
        add_user_to_team(team, admin)
        create_rotation(
            team, name=f"Schedule {index:02d}", users=[admin],
            start_at=utc_now() - timedelta(days=7),
        )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    screenshots = ROOT / "tests/.tmp/release-26-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(admin)[0],
        "screenshots": str(screenshots),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/release_26.browser.js"],
            cwd=ROOT, env={**os.environ, "RELEASE_26_FIXTURE": json.dumps(fixture)},
            capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
