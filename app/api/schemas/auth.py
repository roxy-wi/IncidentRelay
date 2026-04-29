from pydantic import Field

from app.api.schemas.base import ApiModel


class LoginSchema(ApiModel):
    """
    Validate login input.
    """

    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordSchema(ApiModel):
    """
    Validate password change input.
    """

    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)
