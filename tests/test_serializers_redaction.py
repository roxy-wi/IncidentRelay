from app.modules.redaction import REDACTED, redact_secrets, redact_string
from app.services.serializers.alerts import serialize_alert
from app.services.serializers.channels import serialize_channel
from app.services.serializers.routes import serialize_route
from app.services.serializers.teams import serialize_team, serialize_group
from app.services.serializers.users import serialize_user
from tests.factories import (
    attach_channel,
    create_alert,
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
)


def test_serializers_return_public_fields(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)
    channel = create_channel(group, team)
    route = create_route(team)
    attach_channel(route, channel)
    alert = create_alert(route)

    assert serialize_group(group)["slug"] == "infra"
    assert serialize_team(team)["group_slug"] == "infra"
    assert serialize_user(user)["username"] == "alice"
    assert serialize_channel(channel)["channel_type"] == "webhook"
    assert serialize_route(route)["team_slug"] == "sre"
    assert serialize_alert(alert)["title"] == "DiskFull"


def test_redact_string_masks_common_secret_patterns():
    text = "Authorization: Bearer secret-token https://api.telegram.org/bot123456:ABCdefghijklmnopqrstuvwxyz/sendMessage"

    redacted = redact_string(text)

    assert "secret-token" not in redacted
    assert "123456:ABC" not in redacted
    assert REDACTED in redacted


def test_redact_secrets_masks_sensitive_mapping_keys_recursively():
    value = {
        "token": "abc",
        "nested": {
            "password": "secret",
            "safe": "value",
        },
    }

    assert redact_secrets(value) == {
        "token": REDACTED,
        "nested": {
            "password": REDACTED,
            "safe": "value",
        },
    }
