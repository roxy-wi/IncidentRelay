from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """
    Base schema for API request validation.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmptySchema(ApiModel):
    """
    Empty request body schema.
    """


class IdBody(ApiModel):
    """
    Request body containing a user id.
    """

    user_id: Optional[int] = Field(default=None, ge=1)


JsonDict = Dict[str, Any]
JsonList = List[Any]
