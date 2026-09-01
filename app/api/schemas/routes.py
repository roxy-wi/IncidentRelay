from typing import Any, Dict, List
import re

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel
from app.services.notifications.policies.constants import NOTIFICATION_CHANNEL_MODE_PATTERN, ROUTE_ONLY


ROUTE_ESCALATION_MODE_PATTERN = r"^(rotation|policy)$"
AWS_SNS_TOPIC_ARN_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):"
    r"sns:[a-z0-9-]+:\d{12}:"
    r"[A-Za-z0-9_-]{1,256}(?:\.fifo)?$"
)


class RouteBaseSchema(ApiModel):
    """Base schema for alert route input."""

    team_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=120)
    source: str = Field(pattern=r"^(alertmanager|aws_sns|datadog|grafana|zabbix|webhook|sentry|librenms|new_relic|nagios|rmon|uptime_kuma|heartbeat)$")
    rotation_id: int | None = Field(default=None, ge=1)
    channel_ids: List[int] = Field(default_factory=list)
    notification_channel_mode: str = Field(default=ROUTE_ONLY, pattern=NOTIFICATION_CHANNEL_MODE_PATTERN)
    matcher_preset_id: int | None = Field(default=None, ge=1)
    matchers: Dict[str, Any] = Field(default_factory=dict)
    group_by: List[str] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def validate_integration_config(self):
        if self.source != "aws_sns":
            return self

        config = self.integration_config or {}
        aws_sns = config.get("aws_sns")

        if not isinstance(aws_sns, dict):
            raise ValueError(
                "AWS SNS Topic ARN is required"
            )

        topic_arn = str(
            aws_sns.get("topic_arn") or ""
        ).strip()

        if not topic_arn:
            raise ValueError(
                "AWS SNS Topic ARN is required"
            )

        if not AWS_SNS_TOPIC_ARN_PATTERN.fullmatch(
                topic_arn
        ):
            raise ValueError(
                "AWS SNS Topic ARN is invalid"
            )

        return self


class RouteCreateSchema(RouteBaseSchema):
    """Validate alert route creation input."""


class RouteUpdateSchema(RouteBaseSchema):
    """Validate alert route update input."""


class RouteChannelsReplaceSchema(ApiModel):
    """Validate route channel replacement input."""

    channel_ids: List[int] = Field(default_factory=list)
