from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict



class ApiModel(BaseModel):
    """
    Base schema for API request validation.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmptySchema(ApiModel):
    """
    Empty request body schema.
    """


JsonDict = Dict[str, Any]
JsonList = List[Any]
