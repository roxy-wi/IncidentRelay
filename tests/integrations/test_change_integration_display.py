"""Integration labels remain readable without disclosing foreign catalog names."""

import pytest

from app.modules.db.models import Service, Team
from tests.factories import create_group, create_team
from tests.integrations.test_change_integration_groups import (
    headers,
    owned_identity as owned_identity,
)
from tests.integrations.test_change_integrations import BASE, grant


def get_source(client, identity):
    """Read one source through the same authenticated endpoint as the editor."""
    integration, _, _, manager = identity
    response = client.get(f"{BASE}/{integration.id}", headers=headers(manager))
    assert response.status_code == 200
    return response.get_json()["sources"][0]


def test_names_and_slugs_match_target_choices(client, owned_identity):
    integration, _, service, manager = owned_identity
    grant(owned_identity, service=service.id)
    grant(owned_identity, capability="reference")
    source = get_source(client, owned_identity)
    targets = client.get(
        f"{BASE}/targets?integration_id={integration.id}&team_id={service.team_id}",
        headers=headers(manager),
    ).get_json()
    team = targets["teams"][0]
    selected_service = targets["services"][0]
    assert source["owner_team_name"] == team["name"]
    assert source["owner_team_slug"] == team["slug"]
    saved = source["grants"][0]
    assert saved["target_team_name"] == team["name"]
    assert saved["target_team_slug"] == team["slug"]
    assert saved["target_service_name"] == selected_service["name"]
    assert saved["target_service_slug"] == selected_service["slug"]
    assert source["grants"][1]["target_service_id"] is None
    assert source["grants"][1]["target_service_name"] is None


@pytest.mark.parametrize("deleted", [False, True])
def test_renamed_disabled_targets_keep_their_full_names(
    client, owned_identity, deleted
):
    _, _, service, _ = owned_identity
    grant(owned_identity, service=service.id)
    Team.update(name="Infrastructure <platform>", active=False, deleted=deleted).where(
        Team.id == service.team_id
    ).execute()
    Service.update(name="Terraform state & deployment", enabled=False, deleted=deleted).where(
        Service.id == service.id
    ).execute()
    source = get_source(client, owned_identity)
    assert source["owner_team_name"] == "Infrastructure <platform>"
    assert source["grants"][0]["target_team_name"] == "Infrastructure <platform>"
    assert source["grants"][0]["target_service_name"] == "Terraform state & deployment"


def test_moved_team_does_not_disclose_its_new_name(client, owned_identity):
    _, _, service, _ = owned_identity
    grant(owned_identity, service=service.id)
    Team.update(group=create_group(), name="Foreign confidential team").where(
        Team.id == service.team_id
    ).execute()
    source = get_source(client, owned_identity)
    assert source["owner_team_id"] == service.team_id
    assert source["owner_team_name"] is None
    assert source["owner_team_slug"] is None
    saved = source["grants"][0]
    assert saved["target_team_name"] is None
    assert saved["target_service_name"] is None
    assert "Foreign confidential" not in str(source)


def test_moved_service_does_not_disclose_its_new_name(client, owned_identity):
    _, _, service, _ = owned_identity
    grant(owned_identity, service=service.id)
    destination = create_team(create_group())
    Service.update(
        team=destination, group=destination.group_id, name="Foreign confidential service"
    ).where(Service.id == service.id).execute()
    saved = get_source(client, owned_identity)["grants"][0]
    assert saved["target_team_name"] == service.team.name
    assert saved["target_service_id"] == service.id
    assert saved["target_service_name"] is None
    assert saved["target_service_slug"] is None
