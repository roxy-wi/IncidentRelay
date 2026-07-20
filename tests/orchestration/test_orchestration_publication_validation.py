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
from tests.factories import create_group, create_user


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
