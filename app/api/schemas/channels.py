from typing import Any, Dict

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel


class ChannelBaseSchema(ApiModel):
    """Base schema for notification channel input."""

    team_id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=2, max_length=120)
    channel_type: str = Field(
        pattern=r"^(telegram|slack|mattermost|webhook|discord|teams|email|voice_call)$"
    )
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_config(self):
        """Validate channel-specific config fields."""
        config = self.config or {}

        if self.channel_type == "telegram" and (not config.get("bot_token") or not config.get("chat_id")):
            raise ValueError("telegram channel requires bot_token and chat_id")

        if self.channel_type in {"slack", "webhook", "discord", "teams"} and not config.get("webhook_url"):
            raise ValueError(f"{self.channel_type} channel requires webhook_url")

        if self.channel_type == "mattermost":
            mode = config.get("mode") or ("bot_api" if config.get("api_url") else "webhook")
            if mode == "bot_api":
                missing = [name for name in ["api_url", "bot_token", "channel_id"] if not config.get(name)]
                if missing:
                    raise ValueError(f"mattermost Bot API mode requires: {', '.join(missing)}")
            if mode == "webhook" and not config.get("webhook_url"):
                raise ValueError("mattermost webhook mode requires webhook_url")

        if self.channel_type == "email":
            recipients = config.get("recipients")
            if not isinstance(recipients, list) or not recipients:
                raise ValueError("email channel requires recipients list")

        if self.channel_type == "voice_call":
            severities = config.get("call_on_severities") or []

            if not isinstance(severities, list) or not severities:
                raise ValueError("voice_call channel requires call_on_severities list")

            allowed = {"critical", "high", "medium", "warning", "low", "info"}
            invalid = [item for item in severities if item not in allowed]

            if invalid:
                raise ValueError(f"voice_call has invalid severities: {', '.join(invalid)}")

            rules = config.get("notification_rules", [])
            if not isinstance(rules, list):
                raise ValueError("voice_call notification_rules must be a list")

        return self


class ChannelCreateSchema(ChannelBaseSchema):
    """
    Validate notification channel creation input.
    """


class ChannelUpdateSchema(ChannelBaseSchema):
    """
    Validate notification channel update input.
    """
