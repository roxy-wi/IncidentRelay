"""Exercise dashboard filters and navigation against the real alert API."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.db.models import IncidentResponder, UserGroup
from tests.alerts.test_alerts_involvement_filter import alert_group, linked_incident
from tests.factories import (
    create_group,
    create_incident_stakeholder,
    create_service,
    create_team,
    create_user,
)


def test_alert_filter_preferences():
    """Run the production state helper with isolated browser storage and history."""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            shutil.which("node") or "node",
            "--test",
            "tests/ux/alert_filter_state.test.js",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests"
)
def test_dashboard_filters_browser(app, db):
    group = create_group()
    team = create_team(group, name="Platform")
    other_team = create_team(group, name="Network")
    other_group = create_group()
    foreign_team = create_team(other_group, name="Other group team")
    user = create_user(group=group, group_role="user_admin")
    UserGroup.create(user=user, group=other_group, role="user_admin", active=True)
    service = create_service(team, name="Platform API")
    empty_service = create_service(team, name="No active alerts")
    other_service = create_service(other_team, name="Network API")
    foreign_service = create_service(foreign_team, name="Other group API")
    assigned = alert_group(team, "Assigned alert", assignee=user, service=service)
    responder = alert_group(team, "Responder alert", service=service)
    IncidentResponder.create(
        incident=linked_incident(responder), target_type="user", target_user=user
    )
    stakeholder = alert_group(team, "Stakeholder alert", service=service)
    create_incident_stakeholder(linked_incident(stakeholder), user)
    unrelated = alert_group(team, "Unrelated alert", service=service)
    resolved = alert_group(
        team, "Resolved alert", service=service, status="resolved", assignee=user
    )
    other = alert_group(
        other_team, "Network alert", service=other_service, assignee=user
    )
    foreign = alert_group(
        foreign_team, "Other group alert", service=foreign_service, assignee=user
    )
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/dashboard-filters-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(user)[0],
        "team": team.id,
        "otherTeam": other_team.id,
        "group": group.id,
        "otherGroup": other_group.id,
        "foreignTeam": foreign_team.id,
        "service": service.id,
        "emptyService": empty_service.id,
        "otherService": other_service.id,
        "foreignService": foreign_service.id,
        "assigned": assigned.id,
        "responder": responder.id,
        "stakeholder": stakeholder.id,
        "unrelated": unrelated.id,
        "resolved": resolved.id,
        "other": other.id,
        "foreign": foreign.id,
        "screenshots": str(screenshots),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/dashboard_filters.browser.js"],
            cwd=root,
            env={**os.environ, "DASHBOARD_FILTERS_FIXTURE": json.dumps(fixture)},
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
