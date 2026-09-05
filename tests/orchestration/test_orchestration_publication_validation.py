"""Integration checks for the workstream #17 publication validator hook."""

import pytest

from app.modules.db.models import (
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationIntakeToken,
)
from app.modules.db.orchestrations_repo import (
    OrchestrationValidationError,
    create_orchestration,
    get_or_create_draft,
    publish_draft,
    replace_draft_rules,
    validate_version,
)
from tests.factories import create_group, create_service, create_team, create_user


@pytest.fixture(autouse=True)
def orchestration_tables(db):
    db.create_tables(
        [
            EventOrchestration,
            EventOrchestrationVersion,
            EventOrchestrationRule,
            OrchestrationIntakeToken,
            OrchestrationExecution,
        ],
        safe=True,
    )
    yield


def _draft_with_rule(db, condition_tree, actions):
    group = create_group()
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="Validation integration",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [
            {
                "name": "Invalid rule",
                "condition_tree": condition_tree,
                "actions": actions,
            }
        ],
    )
    return user, orchestration, draft


def test_invalid_condition_blocks_publication(db):
    user, orchestration, draft = _draft_with_rule(
        db,
        {"field": "process.__class__", "operator": "exists"},
        [],
    )

    validation = validate_version(draft.id)
    assert validation["valid"] is False
    assert any("field reference" in error for error in validation["errors"])

    with pytest.raises(OrchestrationValidationError):
        publish_draft(orchestration.id, actor_id=user.id)


def test_invalid_template_blocks_publication(db):
    user, orchestration, draft = _draft_with_rule(
        db,
        {},
        [{"type": "set_title", "value": "{{ event.title | attr('__class__') }}"}],
    )

    validation = validate_version(draft.id)
    assert validation["valid"] is False
    assert any("unsupported template filter" in error for error in validation["errors"])

    with pytest.raises(OrchestrationValidationError):
        publish_draft(orchestration.id, actor_id=user.id)


def test_service_orchestration_cannot_change_alert_trace_level(db):
    group = create_group()
    team = create_team(group)
    service = create_service(team, name="Trace service", slug="trace-service")
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="Service trace validation",
        scope="service",
        service_id=service.id,
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [
            {
                "name": "Too late for trace policy",
                "condition_tree": {},
                "actions": [
                    {"type": "set_trace_level", "level": "disabled"}
                ],
            }
        ],
    )

    validation = validate_version(draft.id)

    assert validation["valid"] is False
    assert any(
        "set_trace_level is only supported in global orchestrations" in error
        for error in validation["errors"]
    )
    with pytest.raises(OrchestrationValidationError):
        publish_draft(orchestration.id, actor_id=user.id)


def test_service_orchestration_can_change_alert_event_history(db):
    group = create_group()
    team = create_team(group)
    service = create_service(team, name="History service", slug="history-service")
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="Service history validation",
        scope="service",
        service_id=service.id,
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [
            {
                "name": "Bound noisy history",
                "condition_tree": {},
                "actions": [
                    {"type": "set_alert_event_history", "level": "initial"}
                ],
            }
        ],
    )

    validation = validate_version(draft.id)

    assert validation["valid"] is True
    assert not validation["errors"]
