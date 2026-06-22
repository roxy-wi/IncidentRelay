import pytest
from pydantic import ValidationError

from app.api.schemas.channels import ChannelCreateSchema


def make_slack_schema(config):
    return ChannelCreateSchema(
        name="Production Slack",
        channel_type="slack",
        config=config,
        enabled=True,
    )


def test_slack_bot_api_config_is_valid():
    schema = make_slack_schema(
        {
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": "C0123456789",
            "signing_secret": "test-signing-secret",
        }
    )

    assert schema.config["mode"] == "bot_api"
    assert schema.config["bot_token"] == "xoxb-test-token"
    assert schema.config["channel_id"] == "C0123456789"
    assert schema.config["signing_secret"] == "test-signing-secret"
    assert "webhook_url" not in schema.config


def test_slack_webhook_config_is_valid():
    schema = make_slack_schema(
        {
            "mode": "webhook",
            "webhook_url": (
                "https://hooks.slack.com/services/"
                "TEST/TEST/TEST"
            ),
        }
    )

    assert schema.config["mode"] == "webhook"
    assert schema.config["webhook_url"].startswith(
        "https://hooks.slack.com/"
    )
    assert "bot_token" not in schema.config
    assert "channel_id" not in schema.config


def test_legacy_slack_webhook_defaults_to_webhook_mode():
    schema = make_slack_schema(
        {
            "webhook_url": (
                "https://hooks.slack.com/services/"
                "TEST/TEST/TEST"
            ),
        }
    )

    assert schema.config["mode"] == "webhook"


@pytest.mark.parametrize(
    "config",
    [
        {
            "mode": "bot_api",
            "channel_id": "C0123456789",
        },
        {
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
        },
        {
            "mode": "webhook",
        },
    ],
)
def test_slack_rejects_incomplete_config(config):
    with pytest.raises(ValidationError):
        make_slack_schema(config)


def test_slack_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        make_slack_schema(
            {
                "mode": "socket",
                "bot_token": "xoxb-test-token",
                "channel_id": "C0123456789",
            }
        )


def test_slack_rejects_non_bot_token():
    with pytest.raises(ValidationError):
        make_slack_schema(
            {
                "mode": "bot_api",
                "bot_token": "invalid-token",
                "channel_id": "C0123456789",
            }
        )
