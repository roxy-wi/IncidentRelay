from typing import Any, Dict

from pydantic import Field

from app.api.schemas.base import ApiModel
from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
)


class MatcherPresetCreateSchema(ApiModel):
    """Validate matcher preset creation input."""

    team_id: int = Field(ge=1)

    name: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    matchers: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class MatcherPresetUpdateSchema(ApiModel):
    """Validate partial matcher preset update input."""

    name: str | None = Field(
        default=None,
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )

    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    matchers: Dict[str, Any] | None = None
    enabled: bool | None = None
