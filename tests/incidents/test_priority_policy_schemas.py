import pytest
from pydantic import ValidationError

from app.api.schemas.priority_policies import (
    PriorityPolicyCreateSchema,
    PriorityPolicyRuleCreateSchema,
    PriorityPolicyUpdateSchema,
)


def test_priority_policy_schema_defaults():
    payload = PriorityPolicyCreateSchema(
        team_id=1,
        name="Production priority",
    )

    assert payload.enabled is True
    assert payload.default_for_team is False
    assert payload.update_mode == "raise_only"
    assert payload.source_priority_mode == "ignore"
    assert payload.fallback_mode == "severity_mapping"
    assert payload.fallback_priority_id is None


def test_fixed_fallback_requires_priority():
    with pytest.raises(
        ValidationError,
        match="requires fallback_priority_id",
    ):
        PriorityPolicyCreateSchema(
            team_id=1,
            name="Production priority",
            fallback_mode="fixed_priority",
        )


def test_fixed_fallback_accepts_priority():
    payload = PriorityPolicyCreateSchema(
        team_id=1,
        name="Production priority",
        fallback_mode="fixed_priority",
        fallback_priority_id=3,
    )

    assert payload.fallback_priority_id == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("update_mode", "lower_automatically"),
        ("source_priority_mode", "always"),
        ("fallback_mode", "unknown"),
    ],
)
def test_priority_policy_schema_rejects_unknown_modes(field, value):
    data = {
        "team_id": 1,
        "name": "Production priority",
        field: value,
    }

    with pytest.raises(ValidationError):
        PriorityPolicyCreateSchema(**data)


def test_priority_policy_update_is_partial():
    payload = PriorityPolicyUpdateSchema(enabled=False)

    assert payload.enabled is False
    assert payload.name is None


def test_priority_policy_rule_schema():
    payload = PriorityPolicyRuleCreateSchema(
        name="Critical production",
        matchers={
            "severity": "critical",
            "fields": {
                "service.environment": "production",
            },
        },
        priority_id=1,
    )

    assert payload.position is None
    assert payload.priority_id == 1
    assert payload.enabled is True
