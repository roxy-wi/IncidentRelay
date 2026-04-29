from typing import Any, Dict, List

from pydantic import Field

from app.api.schemas.base import ApiModel


class RouteBaseSchema(ApiModel):
    """
    Base schema for alert route input.
    """

    team_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=120)
    source: str = Field(pattern=r"^(alertmanager|zabbix|webhook)$")
    rotation_id: int | None = Field(default=None, ge=1)
    channel_ids: List[int] = Field(default_factory=list)
    matchers: Dict[str, Any] = Field(default_factory=dict)
    group_by: List[str] = Field(default_factory=list)
    enabled: bool = True


class RouteCreateSchema(RouteBaseSchema):
    """
    Validate alert route creation input.
    """


class RouteUpdateSchema(RouteBaseSchema):
    """
    Validate alert route update input.
    """


class RouteChannelsReplaceSchema(ApiModel):
    """
    Validate route channel replacement input.
    """

    channel_ids: List[int] = Field(default_factory=list)
