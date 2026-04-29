from pydantic import Field

from app.api.schemas.base import ApiModel


class TokenCreateSchema(ApiModel):
    """
    Validate API token creation input.
    """

    team_id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["alerts:write"])
    days: int | None = Field(default=None, ge=1, le=3650)
