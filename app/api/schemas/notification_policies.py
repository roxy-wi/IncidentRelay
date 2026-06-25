from typing import Any, Dict

from pydantic import Field, field_validator

from app.api.schemas.base import ApiModel
from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
)
from app.services.notifications.policies.constants import (
    DEFAULT_NOTIFICATION_POLICY_EVENT_TYPES,
    NOTIFICATION_POLICY_EVENT_TYPES,
)


class NotificationPolicyCreateSchema(ApiModel):
    """Validate notification policy creation input."""

    team_id: int = Field(ge=1)

    name: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    enabled: bool = True


class NotificationPolicyUpdateSchema(ApiModel):
    """Validate notification policy update input."""

    name: str | None = Field(
        default=None,
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    enabled: bool | None = None


class NotificationPolicyRuleCreateSchema(ApiModel):
    """Validate notification policy rule creation input."""

    name: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    position: int | None = Field(
        default=None,
        ge=1,
        le=1000,
    )

    event_types: list[str] = Field(
        default_factory=lambda: list(
            DEFAULT_NOTIFICATION_POLICY_EVENT_TYPES
        )
    )

    matchers: Dict[str, Any] = Field(default_factory=dict)
    matcher_preset_id: int | None = Field(default=None, ge=1)

    channel_ids: list[int] = Field(default_factory=list)

    continue_matching: bool = False
    enabled: bool = True

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, value):
        """Validate and deduplicate event types."""
        values = list(dict.fromkeys(value or []))

        invalid = set(values) - NOTIFICATION_POLICY_EVENT_TYPES

        if invalid:
            raise ValueError(
                "unsupported notification policy event type: "
                + ", ".join(sorted(invalid))
            )

        if not values:
            raise ValueError(
                "notification policy rule requires at least one event type"
            )

        return values

    @field_validator("channel_ids")
    @classmethod
    def validate_channel_ids(cls, value):
        """Validate and deduplicate channel ids."""
        channel_ids = []

        for raw_channel_id in value or []:
            channel_id = int(raw_channel_id)

            if channel_id < 1:
                raise ValueError(
                    "notification policy channel id must be greater than 0"
                )

            if channel_id not in channel_ids:
                channel_ids.append(channel_id)

        return channel_ids


class NotificationPolicyRuleUpdateSchema(ApiModel):
    """Validate notification policy rule update input."""

    name: str | None = Field(
        default=None,
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    position: int | None = Field(
        default=None,
        ge=1,
        le=1000,
    )

    event_types: list[str] | None = None
    matcher_preset_id: int | None = Field(default=None, ge=1)
    matchers: Dict[str, Any] | None = None
    channel_ids: list[int] | None = None

    continue_matching: bool | None = None
    enabled: bool | None = None

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, value):
        """Validate and deduplicate event types."""
        if value is None:
            return None

        values = list(dict.fromkeys(value))

        invalid = set(values) - NOTIFICATION_POLICY_EVENT_TYPES

        if invalid:
            raise ValueError(
                "unsupported notification policy event type: "
                + ", ".join(sorted(invalid))
            )

        if not values:
            raise ValueError(
                "notification policy rule requires at least one event type"
            )

        return values

    @field_validator("channel_ids")
    @classmethod
    def validate_channel_ids(cls, value):
        """Validate and deduplicate channel ids."""
        if value is None:
            return None

        channel_ids = []

        for raw_channel_id in value:
            channel_id = int(raw_channel_id)

            if channel_id < 1:
                raise ValueError(
                    "notification policy channel id must be greater than 0"
                )

            if channel_id not in channel_ids:
                channel_ids.append(channel_id)

        return channel_ids


class NotificationPolicyRuleOrderSchema(ApiModel):
    """Validate an explicit notification policy rule order."""

    rule_ids: list[int] = Field(default_factory=list)

    @field_validator("rule_ids")
    @classmethod
    def validate_rule_ids(cls, value):
        for rule_id in value:
            if rule_id < 1:
                raise ValueError(
                    "notification policy rule id must be greater than 0"
                )

        return value
