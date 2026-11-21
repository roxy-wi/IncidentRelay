"""Application operations keep their transactional guarantees after extraction."""

from unittest.mock import Mock

import pytest

from app.db import database_proxy
from app.modules.db.models import ChangeGraphState, ChangeJob, Service, Team
from app.services import authorization, team_management
from app.services.alerts import group_state
from app.services.service_catalog import mutations as service_mutations
from tests.factories import create_group, create_service, create_team


@pytest.mark.parametrize("resource", ["team", "service"])
def test_authorization_failure_rolls_back_catalog_mutation(db, monkeypatch, resource):
    """The final authorization check stays inside the catalog write transaction."""
    team = create_team(create_group())
    service = create_service(team)
    revision = ChangeGraphState.get_by_id(1).revision
    jobs = list(ChangeJob.select().dicts())
    checks = []

    def reject(team_id, **kwargs):
        assert database_proxy.in_transaction()
        checks.append(team_id)
        raise authorization.AccessDenied("Access was revoked")

    monkeypatch.setattr(authorization, "recheck_team_write", reject)
    with pytest.raises(authorization.AccessDenied):
        if resource == "team":
            team_management.update_team(team.id, {"name": "Unauthorized"})
        else:
            service_mutations.update_service(service.id, {"name": "Unauthorized"})

    assert checks == [team.id]
    assert Team.get_by_id(team.id).name == team.name
    assert Service.get_by_id(service.id).name == service.name
    assert ChangeGraphState.get_by_id(1).revision == revision
    assert list(ChangeJob.select().dicts()) == jobs


def test_terminal_group_operations_do_not_count_another_transition(db, monkeypatch):
    """Metrics remain attached to effective service transitions, including no-ops."""
    team = create_team(create_group())
    record = Mock()
    monkeypatch.setattr(group_state, "record_alert_group_action", record)
    group = group_state.create_alert_group(
        team=team.id, source="manual", group_key="boundary", title="Boundary",
        status="firing",
    )
    group_state.acknowledge_alert_group(group.id)
    group_state.resolve_alert_group(group.id)
    group_state.resolve_alert_group(group.id)
    group_state.acknowledge_alert_group(group.id)

    assert [call.args[0] for call in record.call_args_list] == [
        "created", "acknowledged", "resolved",
    ]
