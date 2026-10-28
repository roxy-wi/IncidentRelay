"""Real-browser workspace regression suite against an isolated Flask database.

Run with INCIDENTRELAY_BROWSER_TESTS=1 and Node's `playwright` installed.
Use PLAYWRIGHT_CHANNEL=chrome for an installed Chrome, or install Chromium
with `npx playwright install chromium`. No production server is used.
"""

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.db.models import Incident, IncidentAlertGroupLink, IncidentEvent
from tests.factories import (
    add_user_to_team, create_group, create_impact_alert_group, create_service,
    create_team, create_user,
)


@pytest.mark.skipif(os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
                    reason="Enable INCIDENTRELAY_BROWSER_TESTS and install Node playwright")
def test_incident_workspace_in_browser(app, db, monkeypatch):
    """Exercise production HTML/JS, real APIs, navigation and failure handling."""
    monkeypatch.setattr("app.services.incidents.stakeholders.notify_stakeholders", lambda *a, **k: None)
    group = create_group()
    team = create_team(group)
    admin = create_user(group=group, is_admin=True)
    user = create_user(group=group)
    add_user_to_team(team, user, role="responder")
    reader = create_user(group=group, group_role="viewer")
    add_user_to_team(team, reader, role="viewer")
    service = create_service(team, name="Workspace service")
    incident = Incident.create(team=team, title="Workspace browser regression")
    alert_group = create_impact_alert_group(team=team, service=service)
    IncidentAlertGroupLink.create(incident=incident, alert_group=alert_group)
    IncidentEvent.create(
        incident=incident, user=admin, event_type="incident_reopened_by_alert_group",
        created_at=datetime(2026, 10, 25, 1, 30),
        data={"from": "resolved", "to": "investigating", "alert_group_id": alert_group.id},
    )
    token, _ = create_access_token(admin)
    reader_token, _ = create_access_token(reader)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "INCIDENT_WORKSPACE_FIXTURE": json.dumps({
        "baseUrl": f"http://127.0.0.1:{server.server_port}", "token": token,
        "readerToken": reader_token, "incidentId": incident.id, "userId": user.id,
        "serviceId": service.id, "groupId": alert_group.id, "actorName": admin.display_name or admin.username,
    })}
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", str(root / "tests/ux/incident_workspace.browser.js")],
            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
