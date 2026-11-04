"""Service policy is opt-in, validated, audited and protected by Service RBAC."""

import pytest
from pydantic import ValidationError

from app.api.schemas.services import ServiceCreateSchema
from app.login import create_access_token
from app.modules.db.models import AuditLog, ChangeGraphState, ChangeJob, Service
from tests.factories import create_group, create_service, create_team, create_user
from tests.services.test_services import service_payload


def test_settings_default_off_and_update_is_audited(client, admin_headers):
    team = create_team(create_group())
    payload = service_payload(team)
    created = client.post("/api/services", json=payload, headers=admin_headers)
    assert created.status_code == 201
    service_id = created.json["id"]
    assert created.json["change_correlation_enabled"] is False
    assert created.json["change_correlation_exclusions"] == []
    revision = ChangeGraphState.get_by_id(1).revision
    rules = [{"source": "heartbeat", "labels": {"environment": "test"}}]
    payload.update(change_correlation_enabled=True, change_correlation_exclusions=rules)
    saved = client.put(
        f"/api/services/{service_id}", json=payload, headers=admin_headers
    )
    assert saved.status_code == 200
    assert saved.json["change_correlation_enabled"] is True
    assert saved.json["change_correlation_exclusions"] == rules
    assert ChangeGraphState.get_by_id(1).revision > revision
    assert ChangeJob.get(ChangeJob.job_type == "discover_graph").state == "pending"
    audit = AuditLog.get(AuditLog.action == "service.update")
    assert audit.data["change_correlation_enabled"] is True
    # Older clients must not accidentally turn a configured policy off.
    legacy = client.put(
        f"/api/services/{service_id}", json=service_payload(team), headers=admin_headers
    )
    assert legacy.status_code == 200
    assert legacy.json["change_correlation_enabled"] is True
    assert legacy.json["change_correlation_exclusions"] == rules
    payload["change_correlation_exclusions"] = []
    assert (
        client.put(
            f"/api/services/{service_id}", json=payload, headers=admin_headers
        ).status_code
        == 200
    )
    assert Service.get_by_id(service_id).change_correlation_exclusions == []


@pytest.mark.parametrize(
    "rules",
    [
        [{}],
        [{"source": ""}],
        [{"labels": {}}],
        [{"labels": {"kind": {"regex": ".*"}}}],
        [{"labels": {"": "value"}}],
        [{"labels": {"key": "x" * 1025}}],
        [{"source": "heartbeat", "unknown": True}],
        [{"source": "heartbeat"}] * 51,
        {"source": "heartbeat"},
        None,
    ],
)
def test_invalid_or_ambiguous_exclusions_are_rejected(db, rules):
    team = create_team(create_group())
    with pytest.raises(ValidationError):
        ServiceCreateSchema.model_validate(
            service_payload(team, change_correlation_exclusions=rules)
        )


def test_foreign_user_cannot_change_policy(client):
    team = create_team(create_group())
    service = create_service(team)
    outsider = create_user(group=create_group())
    token = create_access_token(outsider)[0]
    result = client.put(
        f"/api/services/{service.id}",
        headers={"Authorization": f"Bearer {token}"},
        json=service_payload(team, change_correlation_enabled=True),
    )
    assert result.status_code in {403, 404}
    assert Service.get_by_id(service.id).change_correlation_enabled is False


def test_audit_failure_rolls_back_policy_and_discovery(
    client, admin_headers, monkeypatch
):
    from app.views.services import core

    team = create_team(create_group())
    service = create_service(team)
    revision = ChangeGraphState.get_by_id(1).revision

    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(core, "write_audit", fail)
    response = client.put(
        f"/api/services/{service.id}",
        headers=admin_headers,
        json=service_payload(team, slug=service.slug, change_correlation_enabled=True),
    )
    assert response.status_code == 500
    assert not Service.get_by_id(service.id).change_correlation_enabled
    assert ChangeGraphState.get_by_id(1).revision == revision
    assert not ChangeJob.select().exists()
