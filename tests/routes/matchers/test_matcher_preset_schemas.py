from app.api.schemas.matcher_presets import (
    MatcherPresetCreateSchema,
    MatcherPresetUpdateSchema,
)
from app.api.schemas.notification_policies import (
    NotificationPolicyRuleCreateSchema,
    NotificationPolicyRuleUpdateSchema,
)
from app.api.schemas.priority_policies import (
    PriorityPolicyRuleCreateSchema,
    PriorityPolicyRuleUpdateSchema,
)


def test_matcher_preset_create_schema():
    payload = MatcherPresetCreateSchema(
        team_id=1,
        name="Production services",
        matchers={
            "fields": {
                "service.environment": "production",
            },
        },
    )

    assert payload.enabled is True
    assert payload.matchers["fields"]["service.environment"] == "production"


def test_matcher_preset_update_is_partial():
    payload = MatcherPresetUpdateSchema(enabled=False)

    assert payload.enabled is False
    assert payload.matchers is None


def test_notification_rule_accepts_preset_and_local_matchers():
    payload = NotificationPolicyRuleCreateSchema(
        name="Critical production",
        matcher_preset_id=4,
        matchers={"severity": "critical"},
        channel_ids=[1],
    )

    assert payload.matcher_preset_id == 4
    assert payload.matchers == {"severity": "critical"}


def test_notification_rule_can_clear_preset():
    payload = NotificationPolicyRuleUpdateSchema(
        matcher_preset_id=None,
    )

    assert payload.model_fields_set == {"matcher_preset_id"}
    assert payload.matcher_preset_id is None


def test_priority_rule_accepts_preset_and_local_matchers():
    payload = PriorityPolicyRuleCreateSchema(
        name="Critical production",
        matcher_preset_id=4,
        matchers={"severity": "critical"},
        priority_id=1,
    )

    assert payload.matcher_preset_id == 4
    assert payload.matchers == {"severity": "critical"}


def test_priority_rule_can_clear_preset():
    payload = PriorityPolicyRuleUpdateSchema(
        matcher_preset_id=None,
    )

    assert payload.model_fields_set == {"matcher_preset_id"}
    assert payload.matcher_preset_id is None
