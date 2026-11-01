"""Group administrators cannot acquire central or cross-Group machine authority."""

import pytest

from app.api.schemas.change_integrations import MachineTokenCreate, SourceCreate
from app.login import create_access_token
from app.modules.db import groups_repo, teams_repo
from app.modules.db.models import ApiToken, AuditLog, ChangeIntegration, UserGroup
from app.services.change_intelligence import administration as admin
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    authorize_reference,
    authorized_source,
    valid_machine_token,
)
from tests.factories import create_group, create_service, create_team, create_user
from tests.integrations.test_change_integrations import BASE, grant, revision


def headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def owned_identity(admin_user):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    manager = create_user(group=group, group_role="user_admin")
    integration = admin.create_integration(
        "Owned pipeline", actor_id=manager.id, owner_group_id=group.id
    )
    source = admin.create_source(
        integration.id,
        SourceCreate(expected_revision=1, owner_team_id=team.id, source="deploy"),
        actor_id=manager.id,
    )
    return integration, source, service, manager


@pytest.mark.parametrize(
    "role,allowed", [("viewer", False), ("editor", False), ("user_admin", True)]
)
def test_page_and_api_require_group_admin_role(client, role, allowed):
    user = create_user(group=create_group(), group_role=role)
    expected = 200 if allowed else 403
    assert client.get(BASE, headers=headers(user)).status_code == expected
    assert (
        client.get("/admin/change-integrations", headers=headers(user)).status_code
        == expected
    )


def test_group_admin_sees_only_owned_identities_and_targets(
    client, owned_identity, admin_user
):
    integration, _, service, manager = owned_identity
    other_group = create_group()
    other_team = create_team(other_group)
    other_service = create_service(other_team)
    central = admin.create_integration("Central", actor_id=admin_user.id)
    foreign = admin.create_integration(
        "Foreign", actor_id=admin_user.id, owner_group_id=other_group.id
    )
    auth = headers(manager)
    listed = client.get(BASE, headers=auth).get_json()["items"]
    assert [row["id"] for row in listed] == [integration.id]
    assert listed[0]["owner_group_id"] == service.group_id
    for target in [central.id, foreign.id, 9999999]:
        assert client.get(f"{BASE}/{target}", headers=auth).status_code == 404
        assert (
            client.get(
                f"{BASE}/targets?integration_id={target}", headers=auth
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"{BASE}/{target}",
                headers=auth,
                json={"expected_revision": 1, "active": False},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"{BASE}/{target}/tokens",
                headers=auth,
                json={"expected_revision": 1, "name": "escape"},
            ).status_code
            == 404
        )
    choices = client.get(BASE + "/targets", headers=auth).get_json()
    assert [row["id"] for row in choices["groups"]] == [service.group_id]
    assert [row["id"] for row in choices["teams"]] == [service.team_id]
    assert choices["can_create_central"] is False
    assert (
        client.get(
            f"{BASE}/targets?team_id={other_service.team_id}", headers=auth
        ).get_json()["services"]
        == []
    )


def test_creation_requires_explicit_owned_group(client, owned_identity):
    _, _, service, manager = owned_identity
    auth = headers(manager)
    for group_id in [None, create_group().id, 9999999]:
        assert (
            client.post(
                BASE,
                headers=auth,
                json={
                    "name": "Denied",
                    "owner_group_id": group_id,
                    "owner_team_id": service.team_id,
                },
            ).status_code
            == 403
        )
    response = client.post(
        BASE,
        headers=auth,
        json={
            "name": "Allowed",
            "owner_group_id": service.group_id,
            "owner_team_id": service.team_id,
        },
    )
    assert response.status_code == 201
    assert response.get_json()["owner_group_id"] == service.group_id
    integration_id = response.get_json()["id"]
    assert (
        client.patch(
            f"{BASE}/{integration_id}",
            headers=auth,
            json={"expected_revision": 1, "owner_group_id": None},
        ).status_code
        == 400
    )


@pytest.mark.parametrize("global_admin", [False, True])
def test_owned_integration_cannot_receive_cross_group_sources_or_grants(
    client, owned_identity, admin_user, global_admin
):
    integration, source, service, manager = owned_identity
    foreign = create_service(create_team(create_group()))
    actor = admin_user if global_admin else manager
    auth = headers(actor)
    version = revision(integration)
    assert (
        client.post(
            f"{BASE}/{integration.id}/sources",
            headers=auth,
            json={
                "expected_revision": version,
                "owner_team_id": foreign.team_id,
                "source": "escape",
            },
        ).status_code
        == 403
    )
    url = f"{BASE}/{integration.id}/sources/{source.id}/grants"
    for team_id, service_id in [(foreign.team_id, None), (service.team_id, foreign.id)]:
        assert (
            client.post(
                url,
                headers=auth,
                json={
                    "expected_revision": version,
                    "capability": "changed",
                    "target_team_id": team_id,
                    "target_service_id": service_id,
                },
            ).status_code
            == 403
        )
    assert revision(integration) == version
    choices = client.get(
        f"{BASE}/targets?integration_id={integration.id}", headers=auth
    ).get_json()
    assert [row["id"] for row in choices["teams"]] == [service.team_id]


def test_group_admin_can_edit_grants_and_rotate_credentials(client, owned_identity):
    integration, source, service, manager = owned_identity
    auth = headers(manager)
    base = f"{BASE}/{integration.id}"
    permission = client.post(
        base + f"/sources/{source.id}/grants",
        headers=auth,
        json={
            "expected_revision": revision(integration),
            "capability": "changed",
            "target_team_id": service.team_id,
        },
    )
    assert permission.status_code == 201
    issued = client.post(
        base + "/tokens",
        headers=auth,
        json={"expected_revision": revision(integration), "name": "CI"},
    )
    assert issued.status_code == 201
    old = issued.get_json()
    rotated = client.post(
        base + f"/tokens/{old['credential']['id']}/rotate",
        headers=auth,
        json={"expected_revision": revision(integration), "name": "Replacement"},
    )
    assert rotated.status_code == 201
    assert not ApiToken.get_by_id(old["credential"]["id"]).active
    current = rotated.get_json()
    assert current["token"] != old["token"]
    assert (
        client.post(
            base + f"/tokens/{current['credential']['id']}/revoke",
            headers=auth,
            json={"expected_revision": revision(integration)},
        ).status_code
        == 200
    )
    assert ApiToken.select().where(ApiToken.active == True).count() == 0
    assert (
        client.patch(
            base,
            headers=auth,
            json={"expected_revision": revision(integration), "name": "Renamed"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "revoke", ["membership", "role", "group_disabled", "group_deleted", "user_disabled"]
)
def test_revoked_administrator_cannot_issue_credentials(client, owned_identity, revoke):
    integration, _, service, manager = owned_identity
    auth = headers(manager)
    if revoke in {"membership", "role"}:
        membership = UserGroup.get(UserGroup.user == manager.id)
        groups_repo.update_group_membership(
            membership.id,
            "editor" if revoke == "role" else "user_admin",
            active=revoke != "membership",
        )
    elif revoke == "user_disabled":
        manager.active = False
        manager.save()
    else:
        if revoke == "group_disabled":
            groups_repo.update_group(service.group_id, {"active": False})
        else:
            groups_repo.soft_delete_group(service.group_id)
    response = client.post(
        f"{BASE}/{integration.id}/tokens",
        headers=auth,
        json={"expected_revision": revision(integration), "name": "Denied"},
    )
    assert response.status_code in {401, 403}
    assert ApiToken.select().count() == 0


def test_service_layer_rechecks_group_authority(owned_identity):
    integration, _, _, manager = owned_identity
    membership = UserGroup.get(UserGroup.user == manager.id)
    groups_repo.update_group_membership(membership.id, "viewer")
    with pytest.raises(ChangeIntegration.DoesNotExist):
        admin.issue_token(
            integration.id,
            MachineTokenCreate(expected_revision=revision(integration), name="Denied"),
            actor_id=manager.id,
        )
    assert ApiToken.select().count() == 0


@pytest.mark.parametrize("move_owner", [False, True])
def test_machine_authority_does_not_follow_team_to_another_group(
    owned_identity, move_owner
):
    integration, source, service, actor = owned_identity
    if not move_owner:
        target_team = create_team(service.group)
        service = create_service(target_team)
    grant(owned_identity, team=service.team_id)
    teams_repo.update_team(service.team_id, {"group": create_group().id})
    with pytest.raises(ChangeAccessDenied):
        with authorized_source(integration.id, source.owner_team_id, source.source) as (
            current,
            _,
        ):
            authorize_reference(
                current, "changed", team_id=service.team_id, service_id=service.id
            )


def test_inactive_owner_invalidates_empty_integration_and_credential(owned_identity):
    integration, _, service, actor = owned_identity
    empty = admin.create_integration(
        "Empty", owner_group_id=service.group_id, actor_id=actor.id
    )
    token, _ = admin.issue_token(
        empty.id,
        MachineTokenCreate(expected_revision=1, name="Before disable"),
        actor_id=actor.id,
    )
    groups_repo.update_group(service.group_id, {"active": False})
    assert revision(empty) == 2
    assert not valid_machine_token(token, ChangeIntegration.get_by_id(empty.id))


def test_active_group_filter_does_not_grant_or_remove_authority(client, owned_identity):
    integration, _, _, manager = owned_identity
    other = create_group()
    UserGroup.create(user=manager, group=other, role="editor")
    manager.active_group = other
    manager.save()
    assert [
        row["id"]
        for row in client.get(BASE, headers=headers(manager)).get_json()["items"]
    ] == [integration.id]


def test_owned_mutations_are_audited_in_the_owner_group(owned_identity):
    integration, _, service, manager = owned_identity
    token, raw = admin.issue_token(
        integration.id,
        MachineTokenCreate(
            expected_revision=revision(integration), name="Scoped audit"
        ),
        actor_id=manager.id,
    )
    entry = (
        AuditLog.select()
        .where(AuditLog.action == "change_integration.token_created")
        .get()
    )
    assert entry.group_id == service.group_id
    assert entry.user_id == manager.id
    assert raw not in str(entry.data)
    assert token.token_hash not in str(entry.data)
