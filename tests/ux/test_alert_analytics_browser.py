"""Exercise period metrics and exact record selection against the real API."""

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
from tests.alerts.test_alert_analytics import _analytics_group
from tests.factories import create_group, create_route, create_service, create_team, create_user


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests"
)
def test_alert_analytics_browser(app, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team, service=service)
    admin = create_user(group=group, group_role="user_admin")
    now = utc_now().replace(minute=0, second=0, microsecond=0)

    def add(name, when, occurrences):
        return _analytics_group(
            team=team,
            route=route,
            service=service,
            alertname=name,
            first_seen_at=when,
            status="firing",
            occurrences=occurrences,
        )

    previous = add("Disk <prod>", now - timedelta(days=9), 2)
    current = add("Disk <prod>", now - timedelta(days=1), 5)
    add("Disk <prod> other", now - timedelta(days=1), 1)
    for index in range(27):
        add(f"Paging {index}", now - timedelta(days=1), 0)
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/alert-analytics-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(admin)[0],
        "teamId": team.id,
        "currentId": current.id,
        "previousId": previous.id,
        "screenshots": str(screenshots),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/alert_analytics.browser.js"],
            cwd=root,
            env={**os.environ, "ALERT_ANALYTICS_FIXTURE": json.dumps(fixture)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=150,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
