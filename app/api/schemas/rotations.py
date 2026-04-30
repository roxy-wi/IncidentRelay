from datetime import datetime

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel


INTERVAL_SECONDS = {
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
    "weeks": 604800,
}


class RotationCreateSchema(ApiModel):
    """
    Validate rotation creation input.
    """

    team_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    start_at: datetime
    rotation_type: str = Field(default="daily", pattern=r"^(daily|weekly|custom)$")
    interval_value: int = Field(default=1, ge=1, le=365)
    interval_unit: str = Field(default="days", pattern=r"^(minutes|hours|days|weeks)$")
    handoff_time: str = Field(default="09:00", pattern=r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    handoff_weekday: int | None = Field(default=None, ge=0, le=6)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    duration_seconds: int | None = Field(default=None, ge=60)
    reminder_interval_seconds: int = Field(default=300, ge=60, le=2592000)
    add_team_members: bool = True

    @model_validator(mode="after")
    def set_duration(self):
        """
        Calculate duration from interval fields.
        """

        if self.rotation_type == "daily":
            self.interval_value = 1
            self.interval_unit = "days"
            self.duration_seconds = 86400
        elif self.rotation_type == "weekly":
            self.interval_value = 1
            self.interval_unit = "weeks"
            self.duration_seconds = 604800
            if self.handoff_weekday is None:
                self.handoff_weekday = 0
        elif self.rotation_type == "custom":
            self.duration_seconds = self.interval_value * INTERVAL_SECONDS[self.interval_unit]

        return self


class RotationMemberAddSchema(ApiModel):
    """
    Validate rotation member input.
    """

    user_id: int = Field(ge=1)
    position: int = Field(ge=0, le=1000)


class RotationOverrideCreateSchema(ApiModel):
    """
    Validate rotation override input.
    """

    user_id: int = Field(ge=1)
    starts_at: datetime
    ends_at: datetime
    reason: str | None = None

    @model_validator(mode="after")
    def validate_range(self):
        """
        Validate override time range.
        """

        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be greater than starts_at")
        return self


class RotationUpdateSchema(RotationCreateSchema):
    """
    Validate rotation update input.
    """


class RotationMemberUpdateSchema(ApiModel):
    """
    Validate rotation member update input.
    """

    position: int = Field(ge=0, le=1000)
    active: bool = True
