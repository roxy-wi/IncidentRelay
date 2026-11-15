"""Exercise source setup, preview and apply against the real application API."""

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
from app.services.directory_sync import client as client_module, service
from app.services.directory_sync.fetch import iso
from tests.factories import create_group, create_user
from tests.integrations.test_directory_sync import snapshot  # noqa: F401


@pytest.mark.skipif(os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests")
def test_directory_sync_browser(app, db, request, monkeypatch):
    group = create_group(name="Operations")
    admin = create_user(group=group, group_role="user_admin")
    data = request.getfixturevalue("snapshot")
    monkeypatch.setattr(service, "fetch_snapshot", lambda _client: data)
    monkeypatch.setattr(service, "fetch_current", lambda _client, ids: [
        {"id": key, "status": "active", "user_id": "u1", "valid_until": iso(utc_now() + timedelta(hours=1))}
        for key in ids
    ])
    monkeypatch.setattr(client_module, "_request_once", lambda *_args, **_kwargs: (200, {}, b'{"teams": [{"enrolledScopeUuid": "t1", "name": "Platform"}]}'))
    stop = threading.Event()
    errors = []
    def work():
        while not stop.wait(0.2):
            try:
                with db.connection_context():
                    service.process_due_sources()
                    service.process_due_current()
            except Exception as error:
                errors.append(type(error).__name__)
    worker = threading.Thread(target=work, daemon=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    worker.start()
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/directory-sync-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    fixture = {"baseUrl": f"http://127.0.0.1:{server.server_port}", "token": create_access_token(admin)[0],
               "groupId": group.id, "screenshots": str(screenshots)}
    try:
        result = subprocess.run([shutil.which("node") or "node", "tests/ux/directory_sync.browser.js"],
                                cwd=root, env={**os.environ, "DIRECTORY_SYNC_FIXTURE": json.dumps(fixture)},
                                capture_output=True, text=True, encoding="utf-8", timeout=150)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not errors, errors
    finally:
        stop.set()
        worker.join(timeout=10)
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
