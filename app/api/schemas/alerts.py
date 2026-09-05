from typing import Any

from pydantic import Field, field_validator

from app.api.schemas.base import ApiModel


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
