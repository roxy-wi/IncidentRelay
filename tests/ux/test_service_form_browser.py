"""Service editor regressions against production HTML, JavaScript and APIs."""

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


def test_service_form_translations():
    """Every supported locale supplies the editor labels and validation errors."""
    english = json.loads(
        (ROOT / "app/static/i18n/en/services.json").read_text(encoding="utf-8")
    )
    keys = {key for key in english if key.startswith("services.form.")}
    for locale in ("ru", "de", "fr", "es", "zh"):
        translated = json.loads(
            (ROOT / f"app/static/i18n/{locale}/services.json").read_text(
                encoding="utf-8"
            )
        )
        for key in keys:
            assert translated[key].strip(), (locale, key)


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable INCIDENTRELAY_BROWSER_TESTS and install Node playwright",
)
def test_service_form_in_browser(app, db, tmp_path):
    """Preserve metadata, validate edits, retry failures and render responsively."""
    group = create_group()
    team = create_team(group, name="Platform Engineering")
    admin = create_user(group=group, is_admin=True)
    service = create_service(
        team, name="Payments API", slug="payments-api", service_type="api",
        tier="tier_1", criticality="critical",
    )
    metadata = {
        "owner": "platform-team",
        "pci": True,
        "deployment": {"region": "eu-central", "retries": 0, "enabled": False},
        "notes": None,
    }
    service.metadata = metadata
    service.labels = {"cost_center": "payments"}
    service.tags = ["customer-facing", "pci"]
    service.lifecycle = "development"
    service.public_name = "Payments"
    service.public_description = "Payment processing"
    service.public_order = 0
    service.description = "Payment authorization and transaction processing."
    service.save()
    token, _ = create_access_token(admin)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "SERVICE_FORM_FIXTURE": json.dumps({
            "baseUrl": f"http://127.0.0.1:{server.server_port}",
            "token": token,
            "serviceId": service.id,
            "teamId": team.id,
            "metadata": metadata,
            "screenshotDir": os.environ.get(
                "SERVICE_FORM_SCREENSHOTS", str(tmp_path)
            ),
        }),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/service_form.browser.js"],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=180, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
