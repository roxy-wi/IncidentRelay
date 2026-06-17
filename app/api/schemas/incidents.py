from typing import Literal

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel


IncidentResponderTargetType = Literal[
    "user",
    "team",
    "rotation",
    "escalation_policy",
]

IncidentResponderUpdateStatus = Literal[
    "accepted",
    "declined",
    "expired",
    "resolved",
]


class IncidentResponderCreateSchema(ApiModel):
    """Validate incident responder creation payload."""

    target_type: IncidentResponderTargetType

    target_user_id: int | None = Field(default=None, ge=1)
    target_team_id: int | None = Field(default=None, ge=1)
    target_rotation_id: int | None = Field(default=None, ge=1)
    target_escalation_policy_id: int | None = Field(default=None, ge=1)

    message: str | None = Field(default=None, max_length=2000)
    expires_after_minutes: int | None = Field(default=None, ge=1, le=10080)

    @model_validator(mode="after")
    def validate_target_id(self):
        target_field_by_type = {
            "user": "target_user_id",
            "team": "target_team_id",
            "rotation": "target_rotation_id",
            "escalation_policy": "target_escalation_policy_id",
        }

        required_field = target_field_by_type[self.target_type]

        for field_name in target_field_by_type.values():
            value = getattr(self, field_name)

            if field_name == required_field and value is None:
                raise ValueError(
                    f"{required_field} is required for "
                    f"{self.target_type} responder"
                )

            if field_name != required_field and value is not None:
                raise ValueError(
                    f"{field_name} must not be set for "
                    f"{self.target_type} responder"
                )

        return self


class IncidentResponderUpdateSchema(ApiModel):
    """Validate incident responder status update payload."""

    status: IncidentResponderUpdateStatus
    response_message: str | None = Field(default=None, max_length=2000)
