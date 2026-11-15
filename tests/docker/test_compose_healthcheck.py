"""Run the configured Compose probe against the application's readiness endpoint."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from werkzeug.serving import make_server

from app.views import health_view


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("state", ["ready", "database_down", "pending_migrations"])
def test_compose_probe_requires_database_and_migrations(app, db, monkeypatch, state):
    """A working login page must not turn a failed readiness probe into success."""
    curl = shutil.which("curl")
    if curl is None:
        pytest.skip("curl is required to execute the Compose healthcheck")

    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    checks = re.findall(r"^      test: (\[.*\])$", compose, re.MULTILINE)
    assert len(checks) == 1
    command = json.loads(checks[0])
    assert command[:2] == ["CMD", "curl"]
    target = urlsplit(command[-1])
    assert target.path == "/readyz"

    monkeypatch.setattr(
        health_view,
        "run_readiness_probe",
        lambda: SimpleNamespace(
            database_error=RuntimeError("database unavailable")
            if state == "database_down"
            else None,
            migration_error=None,
            applied=1,
            total=2 if state == "pending_migrations" else 1,
            pending=["pending_migration.py"] if state == "pending_migrations" else [],
        ),
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Keep the configured command and path; only replace the port for isolation.
        command[1] = curl
        command[-1] = f"http://127.0.0.1:{server.server_port}{target.path}"
        result = subprocess.run(
            command[1:],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == (0 if state == "ready" else 22), result.stderr
        if state == "ready":
            assert json.loads(result.stdout)["status"] == "ready"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
