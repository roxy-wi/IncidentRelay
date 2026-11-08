"""Changes Inbox exercised with the real Flask API and two reader roles."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.db.models import ChangeSource
from tests.integrations.test_changes_read import changes, intake, setup_identity

__all__ = ["changes", "intake", "setup_identity"]


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable browser tests and install Node playwright",
)
def test_changes_inbox_in_browser(app, db, changes, tmp_path):
    """Check XSS, filters, navigation, safe projections and failed refreshes."""
    ChangeSource.create(
        integration=changes["change"].integration_id,
        owner_team=changes["change"].owner_team_id,
        source="no-history",
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[2]
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "ownerToken": create_access_token(changes["owner"])[0],
        "readerToken": create_access_token(changes["foreign"])[0],
        "uid": str(changes["change"].uid),
        "title": changes["change"].title,
        "serviceName": changes["service"].name,
        "screenshotDir": str(tmp_path),
        "ownerTeamId": changes["change"].owner_team_id,
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/changes.browser.js"],
            cwd=root,
            env={**os.environ, "CHANGES_FIXTURE": json.dumps(fixture)},
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
