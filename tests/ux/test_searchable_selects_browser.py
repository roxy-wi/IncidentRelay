"""Exercise searchable catalog controls with the real browser and application."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.db.models import Team, UserGroup
from tests.factories import create_group, create_service, create_team, create_user


@pytest.mark.skipif(os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests")
def test_searchable_catalog_selects(app, client, db):
    """Search beyond the first 300 entries and preserve selections on rebuilds."""
    group = create_group()
    with db.atomic():
        Team.insert_many([
            {"group": group.id, "name": f"Catalog team {index:03}", "slug": f"catalog-team-{index}"}
            for index in range(305)
        ]).execute()
    team = create_team(group, name="ZZZ Search target <team>")
    service = create_service(team, name="Search target <service>")
    foreign_group = create_group()
    foreign_team = create_team(foreign_group, name="Foreign team")
    user = create_user(group=group, group_role="editor")
    UserGroup.create(user=user, group=foreign_group, role="editor", active=True)
    token = create_access_token(user)[0]
    created = client.post("/api/event-orchestrations", headers={"Authorization": f"Bearer {token}"}, json={
        "group_id": group.id, "name": "Searchable routing", "scope": "global", "compatibility_mode": "legacy",
    })
    assert created.status_code == 201
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/searchable-selects-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}", "token": token,
        "groupId": group.id, "teamId": team.id, "serviceId": service.id,
        "foreignGroupId": foreign_group.id, "foreignTeamId": foreign_team.id,
        "orchestrationId": created.get_json()["id"], "screenshots": str(screenshots),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/searchable_selects.browser.js"], cwd=root,
            env={**os.environ, "SEARCHABLE_SELECTS_FIXTURE": json.dumps(fixture)},
            capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
