import pytest
from pydantic import ValidationError

from app.api.schemas.channels import ChannelCreateSchema


def test_email_channel_accepts_html_template():
    payload = ChannelCreateSchema.model_validate(
        {
            "team_id": 1,
            "name": "email",
            "channel_type": "email",
            "config": {
                "html_template": """
<h1>{title}</h1>
<p>{message}</p>
""",
            },
            "enabled": True,
        }
    )

    assert payload.config == {
        "html_template": "<h1>{title}</h1>\n<p>{message}</p>"
    }


def test_email_channel_allows_empty_config():
    payload = ChannelCreateSchema.model_validate(
        {
            "team_id": 1,
            "name": "email",
            "channel_type": "email",
            "config": {},
            "enabled": True,
        }
    )

    assert payload.config == {}


def test_email_channel_rejects_invalid_html_template():
    with pytest.raises(ValidationError):
        ChannelCreateSchema.model_validate(
            {
                "team_id": 1,
                "name": "email",
                "channel_type": "email",
                "config": {
                    "html_template": "<h1>{title</h1>",
                },
                "enabled": True,
            }
        )
