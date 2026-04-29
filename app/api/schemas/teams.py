from pydantic import Field

from app.api.schemas.base import ApiModel


class TeamBaseSchema(ApiModel):
    """
    Base schema for team input.
    """

    group_id: int
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    escalation_enabled: bool = True
    escalation_after_reminders: int = Field(default=2, ge=0, le=100)
    active: bool = True


class TeamCreateSchema(TeamBaseSchema):
    """
    Validate team creation input.
    """


class TeamUpdateSchema(TeamBaseSchema):
    """
    Validate team update input.
    """


class TeamUserAddSchema(ApiModel):
    """
    Validate team membership input.
    """

    user_id: int = Field(ge=1)
    role: str = Field(default="read_only", pattern="^(read_only|rw)$")


class TeamUserUpdateSchema(ApiModel):
    """
    Validate team membership update input.
    """

    role: str = Field(default="read_only", pattern="^(read_only|rw)$")
    active: bool = True
