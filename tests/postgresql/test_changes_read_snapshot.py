"""A response must not mix a pre-revocation count with post-revocation links."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api.schemas.change_integrations import GrantUpdate
from app.services.change_intelligence import administration as admin, reading
from tests.integrations.test_changes_read import changes, intake, setup_identity
from tests.integrations.test_change_integration_groups import headers
from tests.integrations.test_change_integrations import revision

__all__ = ["changes", "intake", "setup_identity"]
pytestmark = pytest.mark.postgresql


def test_read_uses_one_snapshot_and_next_request_observes_revocation(
    client, db, changes, monkeypatch
):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")
    original = reading.owner_context
    integration, source, _, actor = changes["intake"][0]

    def revoke():
        with db.connection_context():
            admin.update_grant(
                integration.id,
                source.id,
                changes["permission"].id,
                GrantUpdate(expected_revision=revision(integration), active=False),
                actor_id=actor.id,
            )

    def after_selection(*args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(revoke).result(timeout=10)
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(reading, "owner_context", after_selection)
        response = client.get("/api/changes", headers=headers(changes["foreign"]))
    assert response.status_code == 200, response.json
    assert response.json["pagination"]["total"] == len(response.json["items"]) == 1
    assert len(response.json["items"][0]["services"]) == 1
    assert (
        client.get("/api/changes", headers=headers(changes["foreign"])).json[
            "pagination"
        ]["total"]
        == 0
    )
