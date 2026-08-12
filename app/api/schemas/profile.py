from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import EmailStr, Field, field_validator

from app.api.schemas.base import ApiModel
from app.i18n import normalize_locale
from app.ui_preferences import normalize_theme
from app.api.schemas.limits import (
    CONTACT_ID_MAX_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    TOKEN_NAME_MAX_LENGTH,
    TOKEN_NAME_MIN_LENGTH,
    normalize_phone,
)


class ProfileUpdateSchema(ApiModel):
    """Current user profile update request."""

    display_name: Optional[str] = Field(
        default=None,
        max_length=DISPLAY_NAME_MAX_LENGTH,
    )
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(
        default=None,
        max_length=PHONE_MAX_LENGTH,
    )
    timezone: Optional[str] = Field(default=None, max_length=64)
    locale: Optional[str] = Field(default=None, max_length=16)
    theme: Optional[str] = Field(default=None, max_length=16)
    telegram_user_id: Optional[str] = Field(
        default=None,
        max_length=CONTACT_ID_MAX_LENGTH,
    )
    slack_user_id: Optional[str] = Field(
        default=None,
        max_length=CONTACT_ID_MAX_LENGTH,
    )
    mattermost_user_id: Optional[str] = Field(
        default=None,
        max_length=CONTACT_ID_MAX_LENGTH,
    )
    notify_oncall_shift_start_email: bool | None = None
    notify_oncall_shift_end_email: bool | None = None
    notify_oncall_shift_start_mattermost: bool | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone_field(cls, value):
        """Validate profile phone number."""
        return normalize_phone(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone_field(cls, value):
        """Validate optional IANA timezone name."""
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("invalid timezone") from exc

        return value

    @field_validator("locale")
    @classmethod
    def validate_locale_field(cls, value: str | None) -> str | None:
        """Validate an optional supported interface locale."""
        if value is None:
            return None

        normalized = normalize_locale(value)
        if not normalized:
            raise ValueError("unsupported locale")

        return normalized

    @field_validator("theme")
    @classmethod
    def validate_theme_field(cls, value: str | None) -> str:
        """Validate the interface theme preference."""
        normalized = normalize_theme(value)
        if value is not None and not normalized:
            raise ValueError("unsupported theme")

        return normalized or "system"


class ProfileTokenCreateSchema(ApiModel):
    """Personal API token creation request."""

    name: str = Field(
        default="personal-api-token",
        min_length=TOKEN_NAME_MIN_LENGTH,
        max_length=TOKEN_NAME_MAX_LENGTH,
    )
    group_id: Optional[int] = Field(default=None, ge=1)
    scopes: List[str] = Field(default_factory=lambda: ["alerts:read"])
    days: int = Field(default=0, ge=0, le=365)


class ActiveGroupSchema(ApiModel):
    """Active group selection request."""

    group_id: Optional[int] = Field(default=None, ge=1)
