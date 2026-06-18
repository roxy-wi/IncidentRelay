from typing import Any, Dict, List

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel


ROUTE_ESCALATION_MODE_PATTERN = r"^(rotation|policy)$"


class RouteBaseSchema(ApiModel):
    """Base schema for alert route input."""

    team_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=120)
    source: str = Field(pattern=r"^(alertmanager|zabbix|webhook|sentry|librenms)$")
    rotation_id: int | None = Field(default=None, ge=1)
    channel_ids: List[int] = Field(default_factory=list)
    matchers: Dict[str, Any] = Field(default_factory=dict)
    group_by: List[str] = Field(
        default_factory=lambda: ["alertname", "severity"]
    )
    integration_config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    escalation_mode: str = Field(
        default="rotation",
        pattern=ROUTE_ESCALATION_MODE_PATTERN,
    )
    escalation_policy_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_escalation_policy(self):
        if self.escalation_mode == "policy" and not self.escalation_policy_id:
            raise ValueError("Escalation policy is required when escalation mode is policy")

        if self.escalation_mode != "policy":
            self.escalation_policy_id = None

        return self


class RouteCreateSchema(RouteBaseSchema):
    """Validate alert route creation input."""


class RouteUpdateSchema(RouteBaseSchema):
    """Validate alert route update input."""


class RouteChannelsReplaceSchema(ApiModel):
    """Validate route channel replacement input."""

    channel_ids: List[int] = Field(default_factory=list)
