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
    canonical_json,
    create_intake_token,
    create_orchestration,
    definition_hash,
    get_or_create_draft,
    publish_draft,
    replace_draft_rules,
    revoke_intake_token,
    rollback_to_version,
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


def _fixture():
    group = create_group()
    user = create_user(group=group)
    team = create_team(group)
    service = create_service(team, name="API", slug="api")
    orchestration = create_orchestration(
        group_id=group.id,
        name="Default orchestration",
        created_by_id=user.id,
    )
    return group, user, team, service, orchestration


def _rules(service_id=None):
    actions = [{"type": "set_severity", "value": "critical"}]
    if service_id is not None:
        actions.append({"type": "set_service", "service_id": service_id})
    return [
        {
            "name": "Critical production events",
            "condition_tree": {
                "all": [
                    {"field": "labels.environment", "operator": "eq", "value": "prod"},
                    {"field": "severity", "operator": "eq", "value": "critical"},
                ]
            },
            "actions": actions,
            "processing_mode": "evaluate_children",
            "children": [
                {
                    "name": "Database child",
                    "condition_tree": {
                        "field": "labels.component",
                        "operator": "eq",
                        "value": "database",
                    },
                    "actions": [{"type": "add_label", "key": "tier", "value": "data"}],
                    "processing_mode": "stop",
                }
            ],
        }
    ]


def test_canonical_json_and_hash_are_deterministic():
    left = {"b": 2, "a": {"z": 3, "x": 1}}
    right = {"a": {"x": 1, "z": 3}, "b": 2}

    assert canonical_json(left) == canonical_json(right)
    assert definition_hash(left) == definition_hash(right)


def test_publish_selects_active_version_and_makes_it_immutable(db):
    _, user, _, service, orchestration = _fixture()
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(draft.id, _rules(service.id))

    published = publish_draft(orchestration.id, actor_id=user.id)
    orchestration = EventOrchestration.get_by_id(orchestration.id)

    assert published.status == "published"
    assert orchestration.active_version_id == published.id
    assert published.definition_hash
    assert published.definition_json["rules"][0]["children"][0]["name"] == "Database child"

    published.comment = "must not change"
    with pytest.raises(ValueError, match="immutable"):
        published.save()

    rule = EventOrchestrationRule.get(
        EventOrchestrationRule.version == published.id
    )
    rule.name = "must not change"
    with pytest.raises(ValueError, match="immutable"):
        rule.save()


def test_second_publish_archives_previous_version(db):
    _, user, _, service, orchestration = _fixture()
    first_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(first_draft.id, _rules(service.id))
    first = publish_draft(orchestration.id, actor_id=user.id)

    second_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    cloned_rules = _rules(service.id)
    cloned_rules[0]["name"] = "Changed draft"
    replace_draft_rules(second_draft.id, cloned_rules)
    second = publish_draft(orchestration.id, actor_id=user.id)

    first = EventOrchestrationVersion.get_by_id(first.id)
    assert first.status == "archived"
    assert second.status == "published"
    assert second.version_number == first.version_number + 1
    assert EventOrchestration.get_by_id(orchestration.id).active_version_id == second.id


def test_rollback_creates_new_version_without_mutating_history(db):
    _, user, _, service, orchestration = _fixture()
    first_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(first_draft.id, _rules(service.id))
    first = publish_draft(orchestration.id, actor_id=user.id)

    second_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    changed = _rules(service.id)
    changed[0]["name"] = "Second definition"
    replace_draft_rules(second_draft.id, changed)
    second = publish_draft(orchestration.id, actor_id=user.id)

    rolled_back = rollback_to_version(
        orchestration.id,
        first.id,
        actor_id=user.id,
    )

    first = EventOrchestrationVersion.get_by_id(first.id)
    second = EventOrchestrationVersion.get_by_id(second.id)
    assert first.status == "archived"
    assert second.status == "archived"
    assert rolled_back.status == "published"
    assert rolled_back.id not in {first.id, second.id}
    assert rolled_back.version_number == second.version_number + 1
    assert rolled_back.definition_hash == first.definition_hash



def _failing_update(*args, **kwargs):
    class Query:
        def where(self, *where_args, **where_kwargs):
            return self

        def execute(self):
            raise RuntimeError("forced activation failure")

    return Query()


def test_publish_is_atomic_when_active_pointer_update_fails(db, monkeypatch):
    _, user, _, service, orchestration = _fixture()
    first_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(first_draft.id, _rules(service.id))
    first = publish_draft(orchestration.id, actor_id=user.id)

    second_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    changed = _rules(service.id)
    changed[0]["name"] = "Must remain a draft"
    replace_draft_rules(second_draft.id, changed)

    monkeypatch.setattr(EventOrchestration, "update", _failing_update)
    with pytest.raises(RuntimeError, match="forced activation failure"):
        publish_draft(orchestration.id, actor_id=user.id)

    first = EventOrchestrationVersion.get_by_id(first.id)
    second_draft = EventOrchestrationVersion.get_by_id(second_draft.id)
    orchestration = EventOrchestration.get_by_id(orchestration.id)
    assert first.status == "published"
    assert second_draft.status == "draft"
    assert orchestration.active_version_id == first.id


def test_rollback_is_atomic_when_active_pointer_update_fails(db, monkeypatch):
    _, user, _, service, orchestration = _fixture()
    first_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(first_draft.id, _rules(service.id))
    first = publish_draft(orchestration.id, actor_id=user.id)

    second_draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    changed = _rules(service.id)
    changed[0]["name"] = "Current definition"
    replace_draft_rules(second_draft.id, changed)
    second = publish_draft(orchestration.id, actor_id=user.id)
    version_count = EventOrchestrationVersion.select().where(
        EventOrchestrationVersion.orchestration == orchestration.id
    ).count()

    monkeypatch.setattr(EventOrchestration, "update", _failing_update)
    with pytest.raises(RuntimeError, match="forced activation failure"):
        rollback_to_version(orchestration.id, first.id, actor_id=user.id)

    assert (
        EventOrchestrationVersion.select()
        .where(EventOrchestrationVersion.orchestration == orchestration.id)
        .count()
        == version_count
    )
    assert EventOrchestrationVersion.get_by_id(second.id).status == "published"
    assert EventOrchestration.get_by_id(orchestration.id).active_version_id == second.id

def test_cross_group_service_scope_is_rejected(db):
    group, user, _, _, _ = _fixture()
    other_group = create_group()
    other_team = create_team(other_group)
    foreign_service = create_service(other_team, name="Foreign", slug="foreign")

    with pytest.raises(OrchestrationValidationError, match="another group"):
        create_orchestration(
            group_id=group.id,
            name="Invalid service orchestration",
            scope="service",
            service_id=foreign_service.id,
            created_by_id=user.id,
        )


def test_cross_group_action_reference_is_rejected(db):
    _, user, _, _, orchestration = _fixture()
    other_group = create_group()
    other_team = create_team(other_group)
    foreign_service = create_service(other_team, name="Foreign", slug="foreign")

    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(draft.id, _rules(foreign_service.id))

    result = validate_version(draft.id)
    assert result["valid"] is False
    assert any("another group" in error for error in result["errors"])

    with pytest.raises(OrchestrationValidationError, match="another group"):
        publish_draft(orchestration.id, actor_id=user.id)


def test_new_orchestration_is_disabled_and_preserves_legacy_behavior(db):
    _, _, _, _, orchestration = _fixture()

    assert orchestration.enabled is False
    assert orchestration.mode == "disabled"
    assert orchestration.active_version_id is None


def test_intake_token_is_returned_once_and_can_be_revoked(db):
    _, user, _, _, orchestration = _fixture()

    token, plaintext = create_intake_token(
        orchestration.id,
        name="Migration token",
        actor_id=user.id,
    )

    assert plaintext
    assert plaintext not in token.token_hash
    assert token.token_prefix == plaintext[:12]

    revoked = revoke_intake_token(token.id)
    assert revoked.enabled is False
    assert revoked.revoked_at is not None
