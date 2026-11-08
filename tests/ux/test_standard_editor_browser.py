"""Standard and readiness-check editor regression coverage."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.db.models import ServiceStandard, ServiceStandardCheck
from tests.factories import create_group, create_service, create_team, create_user


ROOT = Path(__file__).resolve().parents[2]


def test_standard_editor_locales():
    """All supported locales have the same standard-editor messages."""
    english = json.loads(
        (ROOT / "app/static/i18n/en/service_standards.json").read_text(
            encoding="utf-8"
        )
    )
    for locale in ("ru", "de", "fr", "es", "zh"):
        translated = json.loads(
            (ROOT / f"app/static/i18n/{locale}/service_standards.json").read_text(
                encoding="utf-8"
            )
        )
        assert english.keys() == translated.keys()
        assert all(value.strip() for value in translated.values())


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable INCIDENTRELAY_BROWSER_TESTS and install Node playwright",
)
def test_standard_editor_in_browser(app, db, tmp_path):
    """Exercise field/value types, filters, drafts, retry and responsive layouts."""
    group = create_group()
    team = create_team(group, name="Platform Engineering")
    create_service(team, name="Payments API")
    admin = create_user(group=group, is_admin=True)
    scope = {
        "kinds": ["technical", "component"],
        "lifecycles": ["production"],
        "environments": ["production", "staging"],
        "tiers": ["tier_1", "tier_2"],
        "criticalities": ["critical", "high"],
        "service_types": ["api", "worker"],
        "labels": {"compliance": ["pci", "soc2"]},
    }
    standard = ServiceStandard.create(
        group=group, slug="production-requirements", name="Production readiness",
        description="Operational requirements for critical production services.",
        applies_to=scope, enabled=True,
    )
    check = ServiceStandardCheck.create(
        standard=standard, slug="description-configured", name="Service description",
        check_type="field_present", configuration={"field": "description"},
        weight=20, position=2, severity="warning", required=True, enabled=True,
    )
    token, _ = create_access_token(admin)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "STANDARD_EDITOR_FIXTURE": json.dumps({
            "baseUrl": f"http://127.0.0.1:{server.server_port}",
            "token": token, "standardId": standard.id, "checkId": check.id,
            "teamId": team.id,
            "scope": scope,
            "screenshotDir": os.environ.get(
                "STANDARD_EDITOR_SCREENSHOTS", str(tmp_path)
            ),
        }),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/standard_editor.browser.js"],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=180, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
