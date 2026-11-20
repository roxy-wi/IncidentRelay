"""Real-browser source creation, discovery, explicit mapping and catalog apply."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.db.models import Service, BusinessService, BusinessServiceComponent
from app.services.sync.directory import service
from tests.integrations.test_cmdb_sync import cmdb_source as cmdb_source, pages as pages, upstream as upstream


@pytest.mark.skipif(os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests")
def test_cmdb_sync_browser(app, db, cmdb_source, upstream, admin_user):
    stop = threading.Event()
    failures = []

    def work():
        while not stop.wait(0.15):
            try:
                with db.connection_context():
                    service.process_due_sources()
            except Exception as error:
                failures.append(type(error).__name__)

    server = make_server("127.0.0.1", 0, app, threaded=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    worker = threading.Thread(target=work, daemon=True)
    server_thread.start()
    worker.start()
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/cmdb-sync-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    fixture = {"baseUrl": f"http://127.0.0.1:{server.server_port}", "token": create_access_token(admin_user)[0],
               "groupId": cmdb_source.group_id, "teams": cmdb_source.config["team_matches"], "screenshots": str(screenshots)}
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/cmdb_sync.browser.js"], cwd=root,
            env={**os.environ, "CMDB_SYNC_FIXTURE": json.dumps(fixture)},
            capture_output=True, text=True, encoding="utf-8", timeout=150,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert not failures
        assert Service.select().count() == BusinessService.select().count() == BusinessServiceComponent.select().count() == 1
    finally:
        stop.set()
        worker.join(timeout=10)
        server.shutdown()
        server_thread.join(timeout=5)
        server.server_close()
