from typing import Any, Dict, List

from pydantic import ConfigDict, Field

from app.api.schemas.base import ApiModel


class AlertmanagerAlertSchema(ApiModel):
    """
    Validate one Alertmanager alert.
    """

    model_config = ConfigDict(extra="ignore")

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    endsAt: str | None = None
    generatorURL: str | None = None
    fingerprint: str | None = None


class AlertmanagerWebhookSchema(ApiModel):
    """
    Validate Alertmanager webhook payload.
    """

    model_config = ConfigDict(extra="ignore")

    receiver: str | None = None
    status: str = "firing"
    alerts: list[AlertmanagerAlertSchema]
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    version: str | None = None
    groupKey: str | None = None
    truncatedAlerts: int | None = None


class ZabbixWebhookSchema(ApiModel):
    """
    Validate Zabbix webhook payload at envelope level.
    """

    event_id: str | None = None
    trigger_id: str | None = None
    title: str | None = None
    subject: str | None = None
    message: str | None = None
    severity: str | None = None
    status: str | None = None
    team: str | None = None
    labels: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str | None = None


class GenericWebhookSchema(ApiModel):
    """
    Validate generic webhook payload.
    """

    title: str = Field(min_length=1, max_length=255)
    message: str | None = None
    severity: str | None = None
    status: str | None = None
    team: str | None = None
    labels: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str | None = None
    external_id: str | None = None
