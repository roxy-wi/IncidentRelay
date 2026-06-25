import pytest
from pydantic import ValidationError

from app.api.schemas.notification_policies import (
    NotificationPolicyCreateSchema,
    NotificationPolicyRuleCreateSchema,
    NotificationPolicyRuleUpdateSchema,
)


def test_notification_policy_create_schema():
    payload = NotificationPolicyCreateSchema(
        team_id=1,
        name="Production notifications",
        description="Production service channels.",
    )

    assert payload.team_id == 1
    assert payload.name == "Production notifications"
    assert payload.enabled is True


def test_notification_policy_rule_defaults():
    payload = NotificationPolicyRuleCreateSchema(
        name="Default delivery",
        channel_ids=[4],
    )

    assert payload.event_types == [
        "notification",
        "reminder",
        "escalation",
    ]

    assert payload.matchers == {}
    assert payload.channel_ids == [4]
    assert payload.continue_matching is False
    assert payload.enabled is True


def test_notification_policy_rule_deduplicates_values():
    payload = NotificationPolicyRuleCreateSchema(
        name="Critical alerts",
        event_types=[
            "notification",
            "notification",
            "escalation",
        ],
        channel_ids=[3, 3, 7],
    )

    assert payload.event_types == [
        "notification",
        "escalation",
    ]

    assert payload.channel_ids == [3, 7]


def test_notification_policy_rule_rejects_unknown_event():
    with pytest.raises(
        ValidationError,
        match="unsupported notification policy event type",
    ):
        NotificationPolicyRuleCreateSchema(
            name="Invalid rule",
            event_types=["resolved"],
            channel_ids=[1],
        )


def test_notification_policy_rule_requires_event_type():
    with pytest.raises(
        ValidationError,
        match="requires at least one event type",
    ):
        NotificationPolicyRuleCreateSchema(
            name="Invalid rule",
            event_types=[],
            channel_ids=[1],
        )


def test_notification_policy_rule_rejects_invalid_channel_id():
    with pytest.raises(
        ValidationError,
        match="channel id must be greater than 0",
    ):
        NotificationPolicyRuleCreateSchema(
            name="Invalid channel",
            channel_ids=[0],
        )


def test_notification_policy_rule_update_is_partial():
    payload = NotificationPolicyRuleUpdateSchema(
        enabled=False,
    )

    assert payload.enabled is False
    assert payload.name is None
    assert payload.channel_ids is None
    assert payload.event_types is None
