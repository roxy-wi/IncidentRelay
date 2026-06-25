from typing import Any, Dict

from pydantic import Field, field_validator, model_validator

from app.api.schemas.base import ApiModel
from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
)
from app.services.incidents.priority_policies.constants import (
    FALLBACK_FIXED_PRIORITY,
    PRIORITY_POLICY_FALLBACK_MODES,
    PRIORITY_POLICY_UPDATE_MODES,
    SOURCE_PRIORITY_MODES,
)


class PriorityPolicyCreateSchema(ApiModel):
    """Validate priority policy creation input."""

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
    default_for_team: bool = False

    update_mode: str = "raise_only"
    source_priority_mode: str = "ignore"
    fallback_mode: str = "severity_mapping"

    fallback_priority_id: int | None = Field(default=None, ge=1)

    @field_validator("update_mode")
    @classmethod
    def validate_update_mode(cls, value):
        if value not in PRIORITY_POLICY_UPDATE_MODES:
            raise ValueError("unsupported priority policy update mode")

        return value

    @field_validator("source_priority_mode")
    @classmethod
    def validate_source_priority_mode(cls, value):
        if value not in SOURCE_PRIORITY_MODES:
            raise ValueError("unsupported source priority mode")

        return value

    @field_validator("fallback_mode")
    @classmethod
    def validate_fallback_mode(cls, value):
        if value not in PRIORITY_POLICY_FALLBACK_MODES:
            raise ValueError("unsupported priority policy fallback mode")

        return value

    @model_validator(mode="after")
    def validate_fallback_priority(self):
        if (
            self.fallback_mode == FALLBACK_FIXED_PRIORITY
            and self.fallback_priority_id is None
        ):
            raise ValueError(
                "fixed priority fallback requires fallback_priority_id"
            )

        return self


class PriorityPolicyUpdateSchema(ApiModel):
    """Validate partial priority policy update input."""

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
    default_for_team: bool | None = None

    update_mode: str | None = None
    source_priority_mode: str | None = None
    fallback_mode: str | None = None

    fallback_priority_id: int | None = Field(default=None, ge=1)

    @field_validator("update_mode")
    @classmethod
    def validate_update_mode(cls, value):
        if value is not None and value not in PRIORITY_POLICY_UPDATE_MODES:
            raise ValueError("unsupported priority policy update mode")

        return value

    @field_validator("source_priority_mode")
    @classmethod
    def validate_source_priority_mode(cls, value):
        if value is not None and value not in SOURCE_PRIORITY_MODES:
            raise ValueError("unsupported source priority mode")

        return value

    @field_validator("fallback_mode")
    @classmethod
    def validate_fallback_mode(cls, value):
        if value is not None and value not in PRIORITY_POLICY_FALLBACK_MODES:
            raise ValueError("unsupported priority policy fallback mode")

        return value


class PriorityPolicyRuleCreateSchema(ApiModel):
    """Validate priority policy rule creation input."""

    name: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    position: int | None = Field(default=None, ge=1, le=1000)

    matchers: Dict[str, Any] = Field(default_factory=dict)
    matcher_preset_id: int | None = Field(default=None, ge=1)

    priority_id: int = Field(ge=1)
    enabled: bool = True


class PriorityPolicyRuleUpdateSchema(ApiModel):
    """Validate partial priority policy rule update input."""

    name: str | None = Field(
        default=None,
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    position: int | None = Field(default=None, ge=1, le=1000)

    matchers: Dict[str, Any] | None = None
    matcher_preset_id: int | None = Field(default=None, ge=1)

    priority_id: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


class PriorityPolicyRuleOrderSchema(ApiModel):
    """Validate complete priority policy rule ordering."""

    rule_ids: list[int] = Field(default_factory=list)

    @field_validator("rule_ids")
    @classmethod
    def validate_rule_ids(cls, value):
        for rule_id in value:
            if rule_id < 1:
                raise ValueError(
                    "priority policy rule id must be greater than 0"
                )

        return value


class PriorityPolicyRuleReorderSchema(ApiModel):
    """Validate complete rule ordering."""

    rule_ids: list[int] = Field(min_length=1)
