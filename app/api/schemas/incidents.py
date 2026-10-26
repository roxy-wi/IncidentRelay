from typing import Literal

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel


IncidentSeverity = Literal[
    "critical",
    "high",
    "medium",
    "low",
    "warning",
    "info",
]

IncidentPrioritySlug = Literal[
    "p1",
    "p2",
    "p3",
    "p4",
    "p5",
]

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


class IncidentCreateSchema(ApiModel):
    """Validate first-class operational Incident creation."""

    team_id: int = Field(ge=1)
    service_id: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    priority: IncidentPrioritySlug | None = None
    assignee_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def normalize_text(self):
        self.title = self.title.strip()
        if self.description is not None:
            self.description = self.description.strip() or None
        return self


class IncidentUpdateSchema(ApiModel):
    """Mutable Incident fields guarded by row_version."""

    row_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    service_id: int | None = Field(default=None, ge=1)
    priority: IncidentPrioritySlug | None = None


class IncidentTransitionSchema(ApiModel):
    row_version: int = Field(ge=1)
    status: Literal["declared", "investigating", "identified", "monitoring", "resolved", "closed", "cancelled"]


class IncidentAssignmentSchema(ApiModel):
    row_version: int = Field(ge=1)
    assignee_id: int | None = Field(default=None, ge=1)


class IncidentLinkSchema(ApiModel):
    alert_group_id: int = Field(ge=1)
    relation_type: Literal["primary", "related"] = "related"


class IncidentParticipantCreateSchema(ApiModel):
    user_id: int = Field(ge=1)
    role: Literal["commander", "responder", "communications"]


class IncidentStakeholderCreateSchema(ApiModel):
    user_id: int | None = Field(default=None, ge=1)
    email: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    role: Literal["stakeholder", "communications", "observer"] = "stakeholder"

    @model_validator(mode="after")
    def validate_target(self):
        if (self.user_id is None) == (not bool(self.email)):
            raise ValueError("Specify exactly one of user_id or email")
        if self.email:
            self.email = self.email.strip().lower()
            if not self.email or "@" not in self.email:
                raise ValueError("Invalid stakeholder email")
        return self


class IncidentCommentCreateSchema(ApiModel):
    body: str = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def normalize_body(self):
        self.body = self.body.strip()
        if not self.body:
            raise ValueError("comment body must not be blank")
        return self


class IncidentAffectedServiceSchema(ApiModel):
    service_id: int = Field(ge=1)


class IncidentFromAlertGroupSchema(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    priority: IncidentPrioritySlug | None = None
    assignee_id: int | None = Field(default=None, ge=1)


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
