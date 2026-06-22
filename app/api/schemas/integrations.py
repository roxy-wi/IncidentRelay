from typing import Any, Dict, List

from pydantic import ConfigDict, Field, model_validator

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
    generatorURL: str | None = None
    silenceURL: str | None = None
    dashboardURL: str | None = None
    panelURL: str | None = None


class GrafanaAlertSchema(ApiModel):
    """Validate one Grafana Alerting alert instance."""

    model_config = ConfigDict(extra="allow")

    status: str = "firing"
    labels: Dict[str, Any] = Field(default_factory=dict)
    annotations: Dict[str, Any] = Field(default_factory=dict)

    startsAt: str | None = None
    endsAt: str | None = None

    generatorURL: str | None = None
    fingerprint: str | None = None
    silenceURL: str | None = None
    dashboardURL: str | None = None
    panelURL: str | None = None

    values: Dict[str, Any] = Field(default_factory=dict)
    valueString: str | None = None


class GrafanaWebhookSchema(ApiModel):
    """Validate a Grafana Alerting webhook payload."""

    model_config = ConfigDict(extra="allow")

    receiver: str | None = None
    status: str = "firing"
    orgId: int | str | None = None

    alerts: List[GrafanaAlertSchema] = Field(min_length=1)

    groupLabels: Dict[str, Any] = Field(default_factory=dict)
    commonLabels: Dict[str, Any] = Field(default_factory=dict)
    commonAnnotations: Dict[str, Any] = Field(default_factory=dict)

    externalURL: str | None = None
    version: str | None = None
    groupKey: str | None = None
    truncatedAlerts: int | None = None

    title: str | None = None
    state: str | None = None
    message: str | None = None


class ZabbixWebhookSchema(ApiModel):
    """Validate Zabbix webhook payload at envelope level."""

    # Zabbix media types are often customized with additional macro fields.
    # Keep known fields typed, but allow extra parameters to pass through
    # to the normalizer.
    model_config = ConfigDict(extra="allow")

    event_id: str | None = None
    eventid: str | None = None

    trigger_id: str | None = None
    triggerid: str | None = None

    title: str | None = None
    subject: str | None = None
    name: str | None = None
    event_name: str | None = None
    trigger_name: str | None = None
    problem_name: str | None = None

    message: str | None = None
    description: str | None = None
    opdata: str | None = None

    severity: str | None = None
    event_severity: str | None = None
    trigger_severity: str | None = None

    status: str | None = None
    event_status: str | None = None

    team: str | None = None

    host: str | None = None
    host_name: str | None = None
    hostname: str | None = None

    labels: Dict[str, Any] = Field(default_factory=dict)

    # Can be a dict, a Zabbix EVENT.TAGSJSON array, or sometimes a raw string.
    tags: Any = None
    event_tag: Any = None
    event_tags: Any = None
    tags_json: Any = None

    fingerprint: str | None = None

    event_link: str | None = None
    event_url: str | None = None
    problem_url: str | None = None
    trigger_url: str | None = None
    zabbix_url: str | None = None

    @model_validator(mode="after")
    def validate_not_empty(self):
        has_identity = bool(
            self.event_id
            or self.eventid
            or self.trigger_id
            or self.triggerid
            or self.fingerprint
        )

        has_content = bool(
            self.title
            or self.subject
            or self.name
            or self.event_name
            or self.trigger_name
            or self.problem_name
            or self.message
            or self.description
            or self.opdata
            or self.event_link
            or self.event_url
            or self.problem_url
            or self.trigger_url
        )

        has_labels = bool(self.labels or self.tags)

        if not (has_identity or has_content or has_labels):
            raise ValueError(
                "Zabbix webhook payload must contain at least one of: "
                "event_id, trigger_id, fingerprint, title, subject, "
                "event_name, trigger_name, problem_name, message, description, "
                "opdata, labels or tags"
            )

        return self


class GenericWebhookSchema(ApiModel):
    """
    Validate generic webhook payload.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=255)
    message: str | None = None
    severity: str | None = None
    status: str | None = None
    team: str | None = None
    labels: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str | None = None
    external_id: str | None = None

    event_link: str | None = None
    event_url: str | None = None
    alert_url: str | None = None
    source_url: str | None = None
    dashboard_url: str | None = None
    runbook_url: str | None = None


class RmonWebhookSchema(ApiModel):
    """Validate an RMON alert payload."""

    model_config = ConfigDict(extra="allow")

    title: str = Field(min_length=1, max_length=255)
    message: str | None = None
    severity: str | None = None
    status: str | None = None

    fingerprint: str | None = None
    external_id: str | int | None = None

    team: str | None = None
    labels: Dict[str, Any] = Field(default_factory=dict)

    runbook: str | None = None
    runbook_url: str | None = None
    event_link: str | None = None

    rmon_name: str | None = None

    check_id: str | int | None = None
    multi_check_id: str | int | None = None
    state_id: str | int | None = None

    check_name: str | None = None
    check_type: str | None = None
    target: str | None = None

    agent: str | None = None
    region: str | None = None
    country: str | None = None


class SentryWebhookSchema(ApiModel):
    """Validate Sentry integration webhook payload."""

    model_config = ConfigDict(extra="allow")

    action: str | None = None
    actor: Dict[str, Any] | None = None
    installation: Dict[str, Any] | None = None
    data: Dict[str, Any] = Field(default_factory=dict)


class LibreNMSWebhookSchema(ApiModel):
    """Validate LibreNMS API transport payload."""

    model_config = ConfigDict(extra="allow")

    id: str | int | None = None
    uid: str | None = None
    alert_id: str | int | None = None
    alert_uid: str | None = None
    external_id: str | int | None = None

    title: str | None = None
    subject: str | None = None
    name: str | None = None
    rule: str | None = None

    message: str | None = None
    msg: str | None = None
    description: str | None = None
    alert_notes: str | None = None

    state: str | int | None = None
    status: str | None = None
    severity: str | None = None

    hostname: str | None = None
    display: str | None = None
    sysName: str | None = None
    device_id: str | int | None = None
    ip: str | None = None
    os: str | None = None
    type: str | None = None
    hardware: str | None = None
    version: str | None = None
    location: str | None = None

    timestamp: str | None = None
    elapsed: str | None = None
    proc: str | None = None

    team: str | None = None
    labels: Dict[str, Any] = Field(default_factory=dict)

    fingerprint: str | None = None
    event_link: str | None = None
    event_url: str | None = None
    alert_url: str | None = None
    source_url: str | None = None
    device_url: str | None = None
    librenms_url: str | None = None

    faults: Any = None
    contacts: Any = None
    applications: Any = None

    @model_validator(mode="after")
    def validate_not_empty(self):
        has_identity = bool(
            self.external_id
            or self.id
            or self.uid
            or self.alert_id
            or self.alert_uid
            or self.fingerprint
        )
        has_content = bool(
            self.title
            or self.subject
            or self.name
            or self.rule
            or self.message
            or self.msg
            or self.description
            or self.hostname
            or self.display
            or self.sysName
        )
        has_labels = bool(self.labels)

        if not (has_identity or has_content or has_labels):
            raise ValueError(
                "LibreNMS webhook payload must contain at least one of: "
                "id, uid, alert_id, title, name, rule, message, msg, "
                "description, hostname, display, sysName, fingerprint or labels"
            )

        return self


class AwsSnsEnvelopeSchema(ApiModel):
    """Validate an Amazon SNS HTTP/HTTPS message envelope."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
    )

    message_type: str = Field(
        alias="Type",
        pattern=(
            r"^(Notification|SubscriptionConfirmation|"
            r"UnsubscribeConfirmation)$"
        ),
    )
    message_id: str = Field(
        alias="MessageId",
        min_length=1,
    )
    topic_arn: str = Field(
        alias="TopicArn",
        min_length=1,
    )
    message: str = Field(
        alias="Message",
    )
    timestamp: str = Field(
        alias="Timestamp",
        min_length=1,
    )
    signature_version: str = Field(
        alias="SignatureVersion",
        pattern=r"^[12]$",
    )
    signature: str = Field(
        alias="Signature",
        min_length=1,
    )
    signing_cert_url: str = Field(
        alias="SigningCertURL",
        min_length=1,
    )

    subject: str | None = Field(
        default=None,
        alias="Subject",
    )
    token: str | None = Field(
        default=None,
        alias="Token",
    )
    subscribe_url: str | None = Field(
        default=None,
        alias="SubscribeURL",
    )
    unsubscribe_url: str | None = Field(
        default=None,
        alias="UnsubscribeURL",
    )
    message_attributes: Dict[str, Any] = Field(
        default_factory=dict,
        alias="MessageAttributes",
    )

    @model_validator(mode="after")
    def validate_confirmation_fields(self):
        if self.message_type in {
            "SubscriptionConfirmation",
            "UnsubscribeConfirmation",
        }:
            if not self.token:
                raise ValueError(
                    "Token is required for an SNS confirmation message"
                )

            if not self.subscribe_url:
                raise ValueError(
                    "SubscribeURL is required for an SNS confirmation message"
                )

        return self
