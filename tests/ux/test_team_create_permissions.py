"""Regression coverage for team managers with read-only group membership."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.db.models import UserGroup
from tests.factories import (
    add_user_to_team,
    create_group,
    create_team,
    create_user,
)


ROOT = Path(__file__).resolve().parents[2]


def test_team_create_permissions_in_javascript():
    """Check button visibility, stale responses and failed permission loads."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    subprocess.run(
        [node, "tests/ux/team_create_permissions.test.js"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )


@pytest.mark.parametrize(
    "group_role,team_role,active_membership,admin,write,resources",
    [
        ("viewer", "manager", True, False, True, True),
        ("viewer", "responder", True, False, False, False),
        ("viewer", "viewer", True, False, False, False),
        ("viewer", None, True, False, False, False),
        ("viewer", "manager", False, False, False, False),
        ("editor", None, True, False, False, True),
        ("user_admin", None, True, False, True, True),
        ("viewer", None, True, True, True, True),
    ],
)
def test_team_api_exposes_create_capabilities(
    client, group_role, team_role, active_membership, admin, write, resources,
):
    """The UI receives distinct strict-team and group-resource permissions."""
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, group_role=group_role, is_admin=admin)
    if team_role:
        membership = add_user_to_team(team, user, team_role)
        membership.active = active_membership
        membership.save()
    response = client.get(
        "/api/teams",
        headers={"Authorization": f"Bearer {create_access_token(user)[0]}"},
    )
    assert response.status_code == 200
    permissions = next(
        item["permissions"] for item in response.get_json() if item["id"] == team.id
    )
    assert permissions["can_write"] is write
    assert permissions["can_write_resources"] is resources


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable browser tests and install Node playwright",
)
def test_team_manager_create_forms_in_browser(app, db):
    """Exercise real forms, read-only choices and active-group switching."""
    empty_group = create_group()
    group = create_group()
    other_group = create_group()
    managed = create_team(group, name="Managed team")
    read_only = create_team(group, name="Read-only team")
    inactive = create_team(group, name="Inactive team")
    inactive.active = False
    inactive.save()
    create_team(other_group, name="Other group team")
    user = create_user(group=group, group_role="viewer")
    add_user_to_team(managed, user, "manager")
    add_user_to_team(read_only, user, "responder")
    add_user_to_team(inactive, user, "manager")
    for extra_group in (empty_group, other_group):
        UserGroup.create(user=user, group=extra_group, role="viewer", active=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(user)[0],
        "teamId": managed.id,
        "readOnlyTeamId": read_only.id,
        "groupId": group.id,
        "otherGroupId": other_group.id,
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/team_create_permissions.browser.js"],
            cwd=ROOT,
            env={**os.environ, "TEAM_CREATE_FIXTURE": json.dumps(fixture)},
            capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
