"""Partial edits to typed, installation-wide settings."""

from typing import Annotated

from pydantic import Field, StrictBool, model_validator

from app.api.schemas.base import ApiModel


PositiveSetting = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]


class SystemSettingsUpdate(ApiModel):
    """Accept only explicitly supplied, non-null settings."""

    change_intake_enabled: StrictBool | None = None
    change_worker_enabled: StrictBool | None = None
    change_max_future_seconds: int | None = Field(default=None, strict=True, ge=0, le=2_147_483_647)
    change_events_per_minute: PositiveSetting | None = None
    change_events_per_change: int | None = Field(default=None, strict=True, ge=1, le=10_000)
    change_worker_interval_seconds: PositiveSetting | None = None
    change_worker_jobs_per_tick: int | None = Field(default=None, strict=True, ge=1, le=100)
    change_worker_batch_size: int | None = Field(default=None, strict=True, ge=1, le=1_000)
    change_worker_lease_seconds: int | None = Field(default=None, strict=True, ge=10, le=2_147_483_647)
    change_worker_max_attempts: PositiveSetting | None = None
    change_worker_retry_base_seconds: PositiveSetting | None = None
    change_worker_retry_max_seconds: PositiveSetting | None = None
    change_pending_ttl_seconds: int | None = Field(default=None, strict=True, ge=60, le=2_147_483_647)
    change_pending_poll_seconds: int | None = Field(default=None, strict=True, ge=5, le=2_147_483_647)

    @model_validator(mode="after")
    def require_setting(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Supply at least one non-null setting")
        return self


def settings_properties():
    """Return the non-null field types and bounds accepted by a partial edit."""
    return {
        name: next(item for item in field["anyOf"] if item["type"] != "null")
        for name, field in SystemSettingsUpdate.model_json_schema()["properties"].items()
    }
