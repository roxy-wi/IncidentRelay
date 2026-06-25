from datetime import datetime
from typing import Any, Dict

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel
from app.api.schemas.limits import DESCRIPTION_MAX_LENGTH


class SilenceCreateSchema(ApiModel):
    """
    Validate silence creation input.
    """

    team_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=20)
    reason: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    matcher_preset_id: int | None = Field(default=None, ge=1)
    matchers: Dict[str, Any] = Field(default_factory=dict)
    starts_at: datetime
    ends_at: datetime
    created_by: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self):
        """
        Validate silence time range.
        """

        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be greater than starts_at")
        return self


class SilenceUpdateSchema(SilenceCreateSchema):
    """
    Validate silence update input.
    """
