"""Silence table information and actions checked against the real API."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from tests.factories import (
    create_group,
    create_matcher_preset,
    create_silence,
    create_team,
    create_user,
)


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable browser tests and install Node playwright",
)
def test_silences_table_in_browser(app, db, tmp_path):
    """Keep all rule data and actions available without the details sidebar."""
    group = create_group()
    team = create_team(group, name="Production Operations", slug="production-ops")
    user = create_user(group=group, is_admin=True)
    preset = create_matcher_preset(team, name="Host maintenance")
    silence = create_silence(
        team,
        matcher_preset=preset,
        matchers={"labels": {"host": "database-" + "x" * 120}},
        apply_to_existing=True,
        reactivate_on_end=False,
    )
    silence.name = "Maintenance <img>"
    silence.reason = (
        "Maintenance reason\n<script>window.silenceInjected=1</script>\n"
        + "Long unbroken explanation " * 2
    )
    silence.save()
    other = create_silence(team)
    other.enabled = False
    other.save()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(user)[0],
        "id": silence.id,
        "name": silence.name,
        "reason": silence.reason,
        "matchers": silence.matchers,
        "otherName": other.name,
        "screenshots": str(tmp_path),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/silences.browser.js"],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "SILENCES_FIXTURE": json.dumps(fixture)},
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
