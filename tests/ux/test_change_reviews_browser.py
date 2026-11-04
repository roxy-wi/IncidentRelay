"""Exercise manual review and Incident link actions against the real API."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from datetime import timedelta

import pytest
from werkzeug.serving import make_server

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db.models import ChangeServiceReference, Incident
from tests.factories import add_user_to_team, create_user
from tests.integrations.test_change_reviews import (
    episode_for,
    intake,
    review_case,
    setup_identity,
)

__all__ = ["intake", "review_case", "setup_identity"]


@pytest.mark.skipif(
    os.environ.get("INCIDENTRELAY_BROWSER_TESTS") != "1",
    reason="Enable Playwright browser checks",
)
def test_change_reviews_in_browser(app, db, review_case, tmp_path):
    case = review_case
    episode = episode_for(case.service, start=utc_now() - timedelta(days=30))
    reference = ChangeServiceReference.get(ChangeServiceReference.change == case.change.id)
    for index in range(26):
        episode_for(case.service)
        Incident.create(team=case.service.team_id, title=f"Other investigation {index}")
        slug = f"future-service-{index}"
        ChangeServiceReference.create(
            change=case.change.id,
            first_event=reference.first_event_id,
            relation_type="changed",
            namespace_team=case.service.team_id,
            ref_type="slug",
            requested_service_slug=slug,
            normalized_ref_key=f"slug:team-id:{case.service.team_id}/{slug}",
        )
    viewer = create_user(group=case.service.team.group, group_role="viewer")
    add_user_to_team(case.service.team, viewer, role="viewer")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = {
        "baseUrl": f"http://127.0.0.1:{server.server_port}",
        "ownerToken": create_access_token(case.user)[0],
        "viewerToken": create_access_token(viewer)[0],
        "uid": str(case.change.uid),
        "correlationId": case.row.id,
        "episodeId": episode.id,
        "incidentId": case.incident.id,
        "serviceName": case.service.name,
        "screenshotDir": str(tmp_path),
    }
    try:
        result = subprocess.run(
            [shutil.which("node") or "node", "tests/ux/change_reviews.browser.js"],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "CHANGE_REVIEW_FIXTURE": json.dumps(fixture)},
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
