from datetime import timedelta, timezone
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from app.api.schemas.base import ApiModel


class AlertActivityQuerySchema(ApiModel):
    """Filters for the cross-group recent activity feed."""

    team_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=6, ge=1, le=25)


class AnalyticsTimezoneQuery(ApiModel):
    """Validate the timezone used for analytics and its drill-down."""

    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Unknown IANA timezone") from error
        return value


class AlertAnalyticsQuerySchema(AnalyticsTimezoneQuery):
    """Validate Alert Analytics v1 query parameters."""

    team_id: int | None = Field(default=None, ge=1)
    days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=10, ge=1, le=50)


class AlertAnalyticsSelectionQuerySchema(AnalyticsTimezoneQuery):
    """Select the exact records behind a period metric or heatmap cell."""

    team_id: int | None = Field(default=None, ge=1)
    since: AwareDatetime
    until: AwareDatetime
    metric: Literal[
        "alert_groups", "occurrences", "ack_rate", "mtta", "mttr", "resolved_without_ack"
    ]
    alertname: (
        Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=5000)]
        | None
    ) = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    hour: int | None = Field(default=None, ge=0, le=23)
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=25, ge=1, le=100)

    @field_validator("since", "until", mode="before")
    @classmethod
    def iso_timestamp(cls, value):
        if not isinstance(value, str) or "T" not in value:
            raise ValueError("Use an ISO timestamp with a timezone")
        return value

    @model_validator(mode="after")
    def valid_selection(self):
        if not timedelta(0) < self.until - self.since <= timedelta(days=365):
            raise ValueError("Select a positive window of at most 365 days")
        if (self.weekday is None) != (self.hour is None):
            raise ValueError("Supply both weekday and hour")
        if self.weekday is not None and self.metric != "alert_groups":
            raise ValueError("Heatmap cells select newly created alert groups")
        if self.alertname is not None and self.metric != "occurrences":
            raise ValueError("Alert names select saved occurrences")
        self.since = self.since.astimezone(timezone.utc).replace(tzinfo=None)
        self.until = self.until.astimezone(timezone.utc).replace(tzinfo=None)
        return self


class AlertEventListQuerySchema(ApiModel):
    """Pagination for alert event history."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class AlertDetailQuerySchema(ApiModel):
    """Optional event pagination embedded in alert-group details."""

    events_page: int | None = Field(default=None, ge=1)
    events_page_size: int | None = Field(default=None, ge=1, le=100)


class AlertListQuerySchema(ApiModel):
    """Validate alert group list query parameters."""

    team_id: int | None = Field(default=None, ge=1)
    status: list[str] = Field(default_factory=list)
    source: list[str] = Field(default_factory=list)
    severity: list[str] = Field(default_factory=list)
    priority: list[str] = Field(default_factory=list)
    service_id: list[int] = Field(default_factory=list)
    service_slug: str | None = Field(default=None, min_length=1, max_length=120)
    service_status: str | None = Field(default=None, min_length=1, max_length=120)
    service_criticality: str | None = Field(default=None, min_length=1, max_length=120)
    search: str | None = Field(default=None, max_length=300)
    assigned_to_me: bool = False
    involvement: Literal["assigned", "responder", "stakeholder", "any"] | None = None
    shelved: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)
    sort: str = Field(
        default="activity",
        pattern=r"^(id|status|title|severity|priority|team|assignee|created|last_seen|activity|reminders)$",
    )
    order: str = Field(default="desc", pattern=r"^(asc|desc)$")
    include_merged: bool = False

    @field_validator("status", "source", "severity", "priority", mode="before")
    @classmethod
    def normalize_string_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []

        values = value if isinstance(value, list) else [value]
        result = []

        for item in values:
            item = str(item).strip()
            if item:
                result.append(item)

        return result

    @field_validator("service_id", mode="before")
    @classmethod
    def normalize_int_list(cls, value: Any) -> list[int]:
        if value is None or value == "":
            return []

        values = value if isinstance(value, list) else [value]
        result = []

        for item in values:
            if item is None or item == "":
                continue
            result.append(int(item))

        return result


class AlertGroupCreateSchema(ApiModel):
    """Validate explicit manual AlertGroup creation."""

    team_id: int = Field(ge=1)
    service_id: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=500)
    message: str | None = Field(default=None, max_length=5000)
    severity: str = Field(default="critical", pattern=r"^(critical|high|medium|low|warning|info)$")
    priority: str | None = Field(default=None, pattern=r"^p[1-5]$")
    notify: bool = True

    @field_validator("title", "message", mode="before")
    @classmethod
    def strip_text(cls, value):
        if value is None:
            return value
        return str(value).strip()


class AlertShelveSchema(ApiModel):
    """Validate one temporary AlertGroup shelf request."""

    duration_seconds: int = Field(default=3600, ge=60, le=604800)
    reason: str | None = Field(default=None, max_length=1000)
