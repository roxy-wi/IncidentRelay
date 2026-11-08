"""Check personal colors through real profile, schedule and incident screens."""

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
from app.modules.db.models import (
    Incident,
    IncidentComment,
    IncidentResponder,
    IncidentStakeholder,
)
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_team,
    create_user,
)


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests"
)
def test_user_colors_in_browser(app, db):
    """The profile color follows an account across pages and survives reload."""
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, is_admin=True)
    user.display_name = "Color <img src=x onerror=window.bad=1>"
    user.save()
    add_user_to_team(team, user)
    create_rotation(team, users=[user], start_at=utc_now() - timedelta(days=7))
    incident = Incident.create(team=team, title="User color preview", assignee=user)
    IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=user,
        status="accepted",
        role="commander",
    )
    IncidentStakeholder.create(incident=incident, user=user)
    IncidentComment.create(incident=incident, author=user, body="Colored author")
    token, _ = create_access_token(user)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "USER_COLORS_FIXTURE": json.dumps(
            {
                "baseUrl": f"http://127.0.0.1:{server.server_port}",
                "token": token,
                "userId": user.id,
                "teamId": team.id,
                "incidentId": incident.id,
            }
        ),
    }
    try:
        result = subprocess.run(
            [
                shutil.which("node") or "node",
                str(root / "tests/ux/user_colors.browser.js"),
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
