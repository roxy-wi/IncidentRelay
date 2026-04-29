from typing import Optional

from pydantic import BaseModel, Field


class GroupCreateSchema(BaseModel):
    """
    Group creation request.
    """

    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None


class GroupUpdateSchema(BaseModel):
    """
    Group update request.
    """

    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    active: bool = True


class UserGroupAddSchema(BaseModel):
    """
    Group membership request.
    """

    user_id: int
    role: str = Field(default="read_only", pattern="^(read_only|rw)$")


class UserGroupUpdateSchema(BaseModel):
    """
    Group membership update request.
    """

    role: str = Field(default="read_only", pattern="^(read_only|rw)$")
    active: bool = True
