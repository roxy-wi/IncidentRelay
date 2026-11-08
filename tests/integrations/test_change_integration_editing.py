"""Atomic default sources, explicit edits, history locks and list counts."""

import pytest

from app.api.schemas.change_integrations import SourceCreate, SourceUpdate, GrantUpdate
from app.modules.db.models import (
    AuditLog,
    Change,
    ChangeGrant,
    ChangeIntegration,
    ChangeSource,
)
from app.services.change_intelligence import administration as admin
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    authorized_source,
    authorize_reference,
)
from tests.factories import create_group, create_service, create_team
from tests.integrations.test_change_integration_groups import (
    headers,
    owned_identity as owned_identity,
)
from tests.integrations.test_change_integrations import BASE, grant, revision


def add_change(integration, source):
    """Represent the first admitted operation without implementing intake."""
    return Change.create(
        source=source,
        integration=integration,
        owner_team=source.owner_team_id,
        external_change_id="first",
        kind="deployment",
        title="First deployment",
    )


def test_creation_provisions_one_source_without_authority(client, owned_identity):
    _, _, service, manager = owned_identity
    payload = {
        "name": "Release Pipeline",
        "owner_group_id": service.group_id,
        "owner_team_id": service.team_id,
    }
    first = client.post(BASE, headers=headers(manager), json=payload)
    second = client.post(BASE, headers=headers(manager), json=payload)
    assert first.status_code == second.status_code == 201
    one, two = first.json, second.json
    assert one["source_count"] == two["source_count"] == 1
    assert one["permission_count"] == 0
    assert one["sources"][0]["source"] == "release-pipeline"
    assert two["sources"][0]["source"] != one["sources"][0]["source"]
    assert one["sources"][0]["owner_team_id"] == service.team_id
    assert one["sources"][0]["identity_editable"] is True
    assert one["tokens"] == [] and one["sources"][0]["grants"] == []


def test_creation_rolls_back_identity_if_source_fails(owned_identity, monkeypatch):
    _, _, service, manager = owned_identity
    identities, sources, audits = (
        ChangeIntegration.select().count(),
        ChangeSource.select().count(),
        AuditLog.select().count(),
    )
    original = admin.audit

    def fail_source_audit(actor_id, action, *args, **kwargs):
        if action == "source_created":
            raise RuntimeError("Audit unavailable")
        return original(actor_id, action, *args, **kwargs)

    monkeypatch.setattr(admin, "audit", fail_source_audit)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        admin.create_integration(
            "Release",
            actor_id=manager.id,
            owner_group_id=service.group_id,
            owner_team_id=service.team_id,
        )
    assert (
        ChangeIntegration.select().count(),
        ChangeSource.select().count(),
        AuditLog.select().count(),
    ) == (identities, sources, audits)


def test_creation_requires_a_team_and_rejects_foreign_scope(client, owned_identity):
    _, _, service, manager = owned_identity
    payload = {"name": "Release", "owner_group_id": service.group_id}
    assert client.post(BASE, headers=headers(manager), json=payload).status_code == 400
    before = ChangeIntegration.select().count()
    payload["owner_team_id"] = create_team(create_group()).id
    assert client.post(BASE, headers=headers(manager), json=payload).status_code == 403
    assert ChangeIntegration.select().count() == before


def test_source_identity_edit_keeps_grants_and_audits_previous_values(
    client, owned_identity
):
    integration, source, service, manager = owned_identity
    permission = grant(owned_identity, service=service.id)
    destination = create_team(service.group)
    response = client.patch(
        f"{BASE}/{integration.id}/sources/{source.id}",
        headers=headers(manager),
        json={
            "expected_revision": revision(integration),
            "source": "renamed",
            "owner_team_id": destination.id,
        },
    )
    assert response.status_code == 200
    saved = ChangeSource.get_by_id(source.id)
    assert (saved.source, saved.owner_team_id) == ("renamed", destination.id)
    assert ChangeGrant.get_by_id(permission.id).source_id == source.id
    audit = (
        AuditLog.select()
        .where(AuditLog.action == "change_integration.source_updated")
        .get()
    )
    assert audit.data["before"]["source"] == source.source
    assert audit.data["after"]["source"] == "renamed"


@pytest.mark.parametrize("field", ["source", "owner_team_id"])
def test_source_history_blocks_identity_but_allows_status_and_order(
    client, owned_identity, field
):
    integration, source, service, manager = owned_identity
    add_change(integration, source)
    version = revision(integration)
    auth = headers(manager)
    url = f"{BASE}/{integration.id}/sources/{source.id}"
    value = "renamed" if field == "source" else create_team(service.group).id
    response = client.patch(
        url, headers=auth, json={"expected_revision": version, field: value}
    )
    assert response.status_code == 409 and revision(integration) == version
    response = client.patch(
        url,
        headers=auth,
        json={
            "expected_revision": version,
            "active": False,
            "ordering_mode": "sequence",
        },
    )
    assert response.status_code == 200
    assert response.json["sources"][0]["identity_editable"] is False
    assert Change.get().ordering_mode == "timestamp"
    assert ChangeSource.get_by_id(source.id).ordering_mode == "sequence"


def test_source_edit_rejects_reserved_namespace_and_foreign_team(owned_identity):
    integration, source, service, manager = owned_identity
    admin.create_source(
        integration.id,
        SourceCreate(
            expected_revision=revision(integration),
            owner_team_id=service.team_id,
            source="reserved",
        ),
        actor_id=manager.id,
    )
    version = revision(integration)
    with pytest.raises(admin.ChangeConflict):
        admin.update_source(
            integration.id,
            source.id,
            SourceUpdate(expected_revision=version, source="reserved"),
            actor_id=manager.id,
        )
    with pytest.raises(ChangeAccessDenied):
        admin.update_source(
            integration.id,
            source.id,
            SourceUpdate(
                expected_revision=version, owner_team_id=create_team(create_group()).id
            ),
            actor_id=manager.id,
        )
    assert revision(integration) == version
    assert ChangeSource.get_by_id(source.id).source == source.source


def test_permission_edit_replaces_authority_and_records_history(owned_identity):
    integration, source, service, manager = owned_identity
    permission = grant(owned_identity, service=service.id)
    target = create_service(create_team(service.group))
    version = revision(integration)
    updated = admin.update_grant(
        integration.id,
        source.id,
        permission.id,
        GrantUpdate(
            expected_revision=version,
            capability="reference",
            target_team_id=target.team_id,
            target_service_id=target.id,
        ),
        actor_id=manager.id,
    )
    assert updated.id == permission.id and ChangeGrant.select().count() == 1
    assert updated.target_key == f"service:{target.id}"
    assert revision(integration) == version + 1
    with authorized_source(integration.id, source.owner_team_id, source.source) as (
        current,
        _,
    ):
        with pytest.raises(ChangeAccessDenied):
            authorize_reference(
                current, "changed", team_id=service.team_id, service_id=service.id
            )
        assert (
            authorize_reference(
                current, "reference", team_id=target.team_id, service_id=target.id
            ).id
            == target.id
        )
    audit = (
        AuditLog.select()
        .where(AuditLog.action == "change_integration.grant_updated")
        .get()
    )
    assert audit.data["before"]["target_service_id"] == service.id
    assert audit.data["after"]["target_service_id"] == target.id


@pytest.mark.parametrize(
    "failure", ["duplicate", "foreign", "wrong_team", "foreign_source"]
)
def test_invalid_permission_edit_preserves_old_authority(
    owned_identity, admin_user, failure
):
    integration, source, service, manager = owned_identity
    permission = grant(owned_identity, service=service.id)
    other_service = create_service(service.team)
    duplicate = grant(owned_identity, service=other_service.id)
    if failure == "duplicate":
        fields, error = {"target_service_id": other_service.id}, admin.ChangeConflict
    elif failure == "foreign":
        foreign = create_service(create_team(create_group()))
        fields, error = (
            {"target_team_id": foreign.team_id, "target_service_id": foreign.id},
            ChangeAccessDenied,
        )
    elif failure == "wrong_team":
        fields, error = (
            {"target_team_id": create_team(service.group).id},
            ChangeAccessDenied,
        )
    else:
        other = admin.create_integration(
            "Other", actor_id=admin_user.id, owner_team_id=service.team_id
        )
        fields, error = (
            {"source_id": ChangeSource.get(ChangeSource.integration == other.id).id},
            ChangeSource.DoesNotExist,
        )
    version = revision(integration)
    before = dict(ChangeGrant.get_by_id(permission.id).__data__)
    with pytest.raises(error):
        admin.update_grant(
            integration.id,
            source.id,
            permission.id,
            GrantUpdate(expected_revision=version, **fields),
            actor_id=manager.id,
        )
    assert dict(ChangeGrant.get_by_id(permission.id).__data__) == before
    assert ChangeGrant.get_by_id(duplicate.id).active
    assert revision(integration) == version


def test_permission_can_move_to_another_source_and_to_whole_team(owned_identity):
    integration, source, service, manager = owned_identity
    permission = grant(owned_identity, service=service.id)
    new_source = admin.create_source(
        integration.id,
        SourceCreate(
            expected_revision=revision(integration),
            owner_team_id=service.team_id,
            source="other",
        ),
        actor_id=manager.id,
    )
    updated = admin.update_grant(
        integration.id,
        source.id,
        permission.id,
        GrantUpdate(
            expected_revision=revision(integration),
            source_id=new_source.id,
            target_service_id=None,
        ),
        actor_id=manager.id,
    )
    assert updated.source_id == new_source.id
    assert (
        updated.target_service_id is None
        and updated.target_key == f"team:{service.team_id}"
    )


def test_permission_audit_failure_rolls_back_edit(owned_identity, monkeypatch):
    integration, source, service, manager = owned_identity
    permission = grant(owned_identity, service=service.id)
    before = dict(permission.__data__)
    version = revision(integration)

    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr(admin, "audit", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        admin.update_grant(
            integration.id,
            source.id,
            permission.id,
            GrantUpdate(expected_revision=version, target_service_id=None),
            actor_id=manager.id,
        )
    assert dict(ChangeGrant.get_by_id(permission.id).__data__) == before
    assert revision(integration) == version


def test_list_counts_include_disabled_records_without_join_multiplication(
    client, owned_identity
):
    integration, source, service, manager = owned_identity
    grant(owned_identity)
    disabled = grant(owned_identity, capability="reference", service=service.id)
    ChangeGrant.update(active=False).where(ChangeGrant.id == disabled.id).execute()
    second = admin.create_source(
        integration.id,
        SourceCreate(
            expected_revision=revision(integration),
            owner_team_id=service.team_id,
            source="second",
        ),
        actor_id=manager.id,
    )
    ChangeSource.update(active=False).where(ChangeSource.id == second.id).execute()
    response = client.get(BASE, headers=headers(manager))
    assert response.status_code == 200
    assert [
        (item["id"], item["source_count"], item["permission_count"])
        for item in response.json["items"]
    ] == [(integration.id, 2, 2)]
    detail = client.get(f"{BASE}/{integration.id}", headers=headers(manager)).json
    assert (detail["source_count"], detail["permission_count"]) == (2, 2)
