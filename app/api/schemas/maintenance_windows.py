from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from pydantic import Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.api.schemas.base import ApiModel
from app.modules.common import as_naive_datetime
from app.modules.common import utc_now


MAINTENANCE_WINDOW_NAME_MAX_LENGTH = 255
MAINTENANCE_WINDOW_DESCRIPTION_MAX_LENGTH = 2000
MAINTENANCE_WINDOW_CANCEL_REASON_MAX_LENGTH = 1000

VALID_MAINTENANCE_BEHAVIORS = {
    "suppress_notifications",
    "suppress_incident",
    "create_maintenance_incident",
    "pause_escalation_only",
}

VALID_SCOPE_TYPES = {
    "group",
    "team",
    "service",
    "route",
}


MaintenanceBehavior = Literal[
    "suppress_notifications",
    "suppress_incident",
    "create_maintenance_incident",
    "pause_escalation_only",
]

MaintenanceScopeType = Literal[
    "group",
    "team",
    "service",
    "route",
]


def validate_rrule_value(value):
    text = str(value or "").strip()

    if not text:
        return None

    if "\n" in text or "\r" in text:
        raise PydanticCustomError(
            "maintenance_rrule",
            "rrule must be a single RRULE value",
        )

    if text.upper().startswith("RRULE:"):
        text = text.split(":", 1)[1].strip()

    try:
        rrulestr(text)
    except (TypeError, ValueError) as exc:
        raise PydanticCustomError(
            "maintenance_rrule",
            "rrule must be a valid RFC5545 RRULE",
        ) from exc

    return text


class MaintenanceWindowScopeSchema(ApiModel):
    """Validate one maintenance window scope."""

    scope_type: MaintenanceScopeType

    group_id: int | None = Field(default=None, ge=1)
    team_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)
    route_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_scope_target(self):
        required_field = f"{self.scope_type}_id"
        required_value = getattr(self, required_field)

        if not required_value:
            raise PydanticCustomError(
                "maintenance_scope_target",
                "{required_field} is required for {scope_type} scope",
                {
                    "required_field": required_field,
                    "scope_type": self.scope_type,
                },
            )

        return self


class MaintenanceWindowBaseSchema(ApiModel):
    """Base schema for maintenance window payloads."""

    name: str = Field(
        min_length=1,
        max_length=MAINTENANCE_WINDOW_NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=MAINTENANCE_WINDOW_DESCRIPTION_MAX_LENGTH,
    )

    behavior: MaintenanceBehavior = "suppress_notifications"

    timezone: str = "UTC"

    rrule: str | None = None

    starts_at: datetime
    ends_at: datetime

    enabled: bool = True
    apply_to_existing: bool = False
    reactivate_on_end: bool = True

    scopes: list[MaintenanceWindowScopeSchema] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        value = str(value or "UTC").strip() or "UTC"

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise PydanticCustomError(
                "maintenance_timezone",
                "timezone must be a valid IANA timezone",
            ) from exc

        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime) -> datetime:
        return as_naive_datetime(value)

    @field_validator("rrule")
    @classmethod
    def normalize_rrule(cls, value):
        return validate_rrule_value(value)

    @model_validator(mode="after")
    def validate_time_range_and_rrule(self):
        if self.ends_at <= self.starts_at:
            raise PydanticCustomError(
                "maintenance_time_range",
                "ends_at must be greater than starts_at",
            )

        zone = ZoneInfo(self.timezone or "UTC")
        local_now = datetime.now(zone).replace(tzinfo=None)

        if self.ends_at <= local_now:
            raise PydanticCustomError(
                "maintenance_time_range",
                "ends_at must be in the future",
            )

        if self.behavior == "suppress_incident" and self.apply_to_existing:
            raise PydanticCustomError(
                "maintenance_behavior",
                "apply_to_existing is not supported for suppress_incident behavior",
            )

        return self


class MaintenanceWindowCreateSchema(MaintenanceWindowBaseSchema):
    """Validate maintenance window creation."""


class MaintenanceWindowUpdateSchema(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    behavior: MaintenanceBehavior | None = None
    timezone: str | None = None
    rrule: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enabled: bool | None = None
    apply_to_existing: bool | None = None
    reactivate_on_end: bool | None = None
    scopes: list[MaintenanceWindowScopeSchema] | None = Field(default=None, min_length=1)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_datetimes(cls, value):
        if value is None:
            return None
        return as_naive_datetime(value)

    @field_validator("rrule")
    @classmethod
    def normalize_rrule(cls, value):
        return validate_rrule_value(value)

    @model_validator(mode="after")
    def validate_update_payload(self):
        if not self.model_fields_set:
            raise PydanticCustomError(
                "maintenance_update",
                "at least one field must be provided",
            )

        if self.starts_at is not None and self.ends_at is not None:
            if self.ends_at <= self.starts_at:
                raise PydanticCustomError(
                "maintenance_time_range",
                "ends_at must be greater than starts_at",
            )

        if self.behavior == "suppress_incident" and self.apply_to_existing:
            raise PydanticCustomError(
                "maintenance_behavior",
                "apply_to_existing is not supported for suppress_incident behavior",
            )

        if self.ends_at is not None:
            zone_name = self.timezone or "UTC"

            try:
                zone = ZoneInfo(zone_name)
            except ZoneInfoNotFoundError:
                zone = ZoneInfo("UTC")

            local_now = datetime.now(zone).replace(tzinfo=None)

            if self.ends_at <= local_now:
                raise PydanticCustomError(
                "maintenance_time_range",
                "ends_at must be in the future",
            )

        return self


class MaintenanceWindowExtendSchema(ApiModel):
    """Validate maintenance window extension."""

    ends_at: datetime

    @field_validator("ends_at")
    @classmethod
    def normalize_ends_at(cls, value: datetime) -> datetime:
        return as_naive_datetime(value)

    @model_validator(mode="after")
    def validate_ends_at(self):
        if self.ends_at <= utc_now():
            raise PydanticCustomError(
                "maintenance_time_range",
                "ends_at must be in the future",
            )

        return self


class MaintenanceWindowCancelSchema(ApiModel):
    """Validate maintenance window cancellation."""

    reason: str | None = Field(
        default=None,
        max_length=MAINTENANCE_WINDOW_CANCEL_REASON_MAX_LENGTH,
    )
