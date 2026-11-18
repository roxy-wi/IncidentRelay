"""Exercise membership summaries in the real profile and admin user modal."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from tests.factories import add_user_to_team, create_group, create_team, create_user


@pytest.mark.skipif(os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests")
def test_user_team_memberships_in_browser(app):
    """Render each user's own memberships, clear old rows, and preserve read-only behavior."""
    group = create_group(name="Operations <img src=x onerror=window.bad=1>")
    admin = create_user(group=group, is_admin=True)
    target = create_user(username="membership-target", group=group)
    empty = create_user(username="membership-empty", group=group)
    shared = create_team(group, name="Shared on-call")
    own = create_team(group, name="Profile only")
    disabled = create_team(group, name="Disabled team <img src=x onerror=window.bad=1>")
    disabled.active = False
    disabled.save()
    add_user_to_team(shared, admin, "responder")
    add_user_to_team(own, admin, "manager")
    add_user_to_team(shared, target, "viewer")
    add_user_to_team(disabled, target, "manager")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/user-team-memberships-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(admin)[0],
        "emptyToken": create_access_token(empty)[0],
        "targetName": target.display_name,
        "emptyName": empty.display_name,
        "sharedId": shared.id,
        "ownId": own.id,
        "disabledId": disabled.id,
        "disabledName": disabled.name,
        "groupName": group.name,
        "screenshots": str(screenshots),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/user_team_memberships.browser.js"],
            cwd=root, env={**os.environ, "USER_TEAMS_FIXTURE": json.dumps(fixture)},
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
