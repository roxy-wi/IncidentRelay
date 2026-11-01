"""The integration administrator can provision and rotate credentials in the UI."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from tests.factories import create_group, create_service, create_team, create_user

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable INCIDENTRELAY_BROWSER_TESTS and install Node playwright",
)
@pytest.mark.parametrize("group_admin", [False, True])
def test_change_integrations_in_browser(app, db, tmp_path, group_admin):
    """Provision, edit grants, retry a failure and rotate with real backend calls."""
    group = create_group()
    team = create_team(group, name="Infrastructure <platform>", slug="infra-platform")
    service = create_service(team, name="Terraform state & deployment", slug="terraform-state")
    admin = create_user(group=group, group_role="user_admin", is_admin=not group_admin)
    token, _ = create_access_token(admin)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "CHANGE_INTEGRATIONS_FIXTURE": json.dumps(
            {
                "baseUrl": f"http://127.0.0.1:{server.server_port}",
                "token": token,
                "teamId": team.id,
                "teamLabel": f"{team.name} ({team.slug})",
                "serviceId": service.id,
                "serviceLabel": f"{service.name} ({service.slug})",
                "groupId": group.id,
                "groupAdmin": group_admin,
                "screenshotDir": str(tmp_path),
            }
        ),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/change_integrations.browser.js"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
