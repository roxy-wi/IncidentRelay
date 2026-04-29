from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class ProfileUpdateSchema(BaseModel):
    """
    Current user profile update request.
    """

    display_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    slack_user_id: Optional[str] = None
    mattermost_user_id: Optional[str] = None


class ProfileTokenCreateSchema(BaseModel):
    """
    Personal API token creation request.
    """

    name: str = Field(default="personal-api-token", min_length=1, max_length=255)
    group_id: Optional[int] = None
    scopes: List[str] = Field(default_factory=lambda: ["alerts:read"])
    days: int = Field(default=0, ge=0)


class ActiveGroupSchema(BaseModel):
    """
    Active group selection request.
    """

    group_id: Optional[int] = None
