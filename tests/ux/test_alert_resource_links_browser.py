"""Verify resource buttons on the real alert details page."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from tests.alerts.test_alert_resource_links import stored_alert_with_links  # noqa: F401
from tests.factories import create_user


@pytest.mark.skipif(os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests")
def test_alert_resource_links_in_browser(app, stored_alert_with_links):  # noqa: F811
    alert, group = stored_alert_with_links
    admin = create_user(is_admin=True)
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/alert-resource-links-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(admin)[0],
        "groupId": group.id,
        "source": alert.payload["generatorURL"],
        "dashboard": alert.payload["annotations"]["dashboard_url"],
        "runbook": alert.payload["annotations"]["runbook_url"],
        "screenshots": str(screenshots),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/alert_resource_links.browser.js"],
            cwd=root, env={**os.environ, "ALERT_LINKS_FIXTURE": json.dumps(fixture)},
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
