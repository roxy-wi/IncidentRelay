from typing import Any, Dict

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel
from app.notifiers.types import CHANNEL_TYPE_PATTERN, WEBHOOK_STYLE_CHANNELS, SLACK_CHANNEL
from app.notifiers.email.email_templates import normalize_email_html_template
from app.services.severity import normalize_severity_list


class ChannelBaseSchema(ApiModel):
    """Base schema for notification channel input."""

    team_id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=2, max_length=120)
    channel_type: str = Field(pattern=CHANNEL_TYPE_PATTERN)
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_config(self):
        """Validate channel-specific config fields."""
        config = dict(self.config or {})

        try:
            notify_on_severities = normalize_severity_list(
                config.get("notify_on_severities")
            )
        except ValueError as exc:
            raise ValueError(f"channel notify_on_severities {exc}") from exc

        if notify_on_severities:
            config["notify_on_severities"] = notify_on_severities
        else:
            config.pop("notify_on_severities", None)

        if self.channel_type == "telegram":
            bot_token = str(config.get("bot_token") or "").strip()
            chat_id = str(config.get("chat_id") or "").strip()

            if not bot_token or not chat_id:
                raise ValueError("telegram channel requires bot_token and chat_id")

            if ":" not in bot_token:
                raise ValueError("telegram bot_token must contain ':'")

            config["bot_token"] = bot_token
            config["chat_id"] = chat_id

        if self.channel_type == SLACK_CHANNEL:
            configured_mode = str(config.get("mode") or "").strip()

            if configured_mode:
                mode = configured_mode
            elif config.get("bot_token") or config.get("channel_id"):
                mode = "bot_api"
            else:
                mode = "webhook"

            if mode not in {"bot_api", "webhook"}:
                raise ValueError(
                    "slack mode must be bot_api or webhook"
                )

            config["mode"] = mode

            if mode == "bot_api":
                bot_token = str(
                    config.get("bot_token") or ""
                ).strip()

                channel_id = str(
                    config.get("channel_id") or ""
                ).strip()

                missing = [
                    name
                    for name in (
                        "bot_token",
                        "channel_id",
                        "signing_secret",
                    )
                    if not str(config.get(name) or "").strip()
                ]

                if missing:
                    raise ValueError(
                        "slack Bot API mode requires: "
                        + ", ".join(missing)
                    )

                if not bot_token.startswith("xoxb-"):
                    raise ValueError(
                        "slack bot_token must start with 'xoxb-'"
                    )

                config["bot_token"] = str(
                    config["bot_token"]
                ).strip()

                config["channel_id"] = str(
                    config["channel_id"]
                ).strip()

                config["signing_secret"] = str(
                    config["signing_secret"]
                ).strip()
                config.pop("webhook_url", None)

            else:
                webhook_url = str(
                    config.get("webhook_url") or ""
                ).strip()

                if not webhook_url:
                    raise ValueError(
                        "slack webhook mode requires webhook_url"
                    )

                config["webhook_url"] = webhook_url
                config.pop("bot_token", None)
                config.pop("channel_id", None)

        if self.channel_type in WEBHOOK_STYLE_CHANNELS and not config.get("webhook_url"):
            raise ValueError(f"{self.channel_type} channel requires webhook_url")

        if self.channel_type == "mattermost":
            mode = config.get("mode") or ("bot_api" if config.get("api_url") else "webhook")
            if mode == "bot_api":
                missing = [
                    name
                    for name in ["api_url", "bot_token", "channel_id"]
                    if not config.get(name)
                ]
                if missing:
                    raise ValueError(
                        f"mattermost Bot API mode requires: {', '.join(missing)}"
                    )
            if mode == "webhook" and not config.get("webhook_url"):
                raise ValueError("mattermost webhook mode requires webhook_url")

        if self.channel_type == "email":
            html_template = normalize_email_html_template(config.get("html_template"))
            if html_template:
                config["html_template"] = html_template
            else:
                config.pop("html_template", None)

        self.config = config
        return self


class ChannelCreateSchema(ChannelBaseSchema):
    """Validate notification channel creation input."""


class ChannelUpdateSchema(ChannelBaseSchema):
    """Validate notification channel update input."""
