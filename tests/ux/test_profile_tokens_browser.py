"""Verify token copy controls remain readable and functional in both themes."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token


@pytest.mark.skipif(os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1", reason="Enable browser tests")
def test_profile_token_copy_in_browser(app, admin_user):
    """Generate and copy a token using the actual profile page and API."""
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[2]
    screenshots = root / "tests/.tmp/profile-token-browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "token": create_access_token(admin_user)[0],
        "screenshots": str(screenshots),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/profile_tokens.browser.js"],
            cwd=root, env={**os.environ, "PROFILE_TOKENS_FIXTURE": json.dumps(fixture)},
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
