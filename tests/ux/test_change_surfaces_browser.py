"""Related Changes share real review APIs across Alerts, Incidents and Services."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db.models import (
    AlertGroupEpisode,
    ChangeAlertGroupCorrelation,
    Incident,
    TeamUser,
    UserGroup,
)
from tests.factories import add_user_to_team
from tests.integrations.test_changes_read import changes
from tests.integrations.test_change_events import intake, setup_identity
from tests.integrations.test_change_correlation import episode_for, run_change

__all__ = ["changes", "intake", "setup_identity"]


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable Playwright browser checks",
)
def test_related_changes_in_browser(app, db, changes, tmp_path):
    service = changes["service"]
    TeamUser.update(role="responder").where(
        TeamUser.user == changes["foreign"].id
    ).execute()
    UserGroup.create(
        user=changes["owner"], group=service.team.group_id, role="viewer", active=True
    )
    add_user_to_team(service.team, changes["owner"], role="responder")
    first = episode_for(service)
    ChangeAlertGroupCorrelation.create(
        change=changes["change"],
        episode=first,
        score=None,
        reason="manual",
        engine_version="manual",
        review_status="confirmed",
        relation_type="mitigation",
    )
    AlertGroupEpisode.update(state="resolved", ended_at=utc_now()).where(
        AlertGroupEpisode.id == first.id
    ).execute()
    second = AlertGroupEpisode.create(
        alert_group=first.alert_group_id,
        ordinal=2,
        started_at=utc_now(),
        start_quality="exact",
    )
    incident = Incident.create(team=service.team_id, title="Investigation workspace")
    run_change(changes["change"], "sync_service_timeline")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "ownerToken": create_access_token(changes["owner"])[0],
        "foreignToken": create_access_token(changes["foreign"])[0],
        "uid": str(changes["change"].uid),
        "groupId": first.alert_group_id,
        "firstEpisode": first.id,
        "secondEpisode": second.id,
        "incidentId": incident.id,
        "serviceId": service.id,
        "screenshotDir": str(tmp_path),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/change_surfaces.browser.js"],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "CHANGE_SURFACES_FIXTURE": json.dumps(fixture)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
