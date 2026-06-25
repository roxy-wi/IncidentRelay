from typing import Any, Dict

from pydantic import Field

from app.api.schemas.base import ApiModel


class MatcherPreviewSchema(ApiModel):
    """Validate matcher preview input."""

    team_id: int = Field(ge=1)
    route_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)
    matcher_preset_id: int | None = Field(default=None, ge=1)
    matchers: Dict[str, Any] = Field(default_factory=dict)
    scan_limit: int = Field(default=200, ge=1, le=500)
    result_limit: int = Field(default=20, ge=1, le=100)
