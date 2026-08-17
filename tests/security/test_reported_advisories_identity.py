import hmac

from app.api.schemas.silences import SilenceCreateSchema
from app.notifiers.mattermost.actions import (
    build_mattermost_action_signature,
    verify_mattermost_action_signature,
)
from app.services.notifications.rules import build_voice_rule_callback_url
from app.settings import Config


def test_mattermost_action_uses_signature_not_shared_secret():
    signature = build_mattermost_action_signature(
        "server-only-secret",
        "resolve",
        42,
        7,
    )

    assert signature != "server-only-secret"
    assert verify_mattermost_action_signature(
        "server-only-secret",
        signature,
        "resolve",
        42,
        7,
    ) is True
    assert verify_mattermost_action_signature(
        "server-only-secret",
        signature,
        "resolve",
        43,
        7,
    ) is False


def test_mattermost_action_signature_comparison_is_constant_time(monkeypatch):
    calls = []

    def fake_compare(left, right):
        calls.append((left, right))
        return False

    monkeypatch.setattr(hmac, "compare_digest", fake_compare)

    assert verify_mattermost_action_signature(
        "secret",
        "invalid",
        "acknowledge",
        1,
        2,
    ) is False
    assert calls


def test_silence_schema_rejects_client_supplied_created_by():
    payload = {
        "team_id": 1,
        "name": "deploy",
        "matchers": {},
        "starts_at": "2030-01-01T00:00:00Z",
        "ends_at": "2030-01-01T01:00:00Z",
        "created_by": 999,
    }

    try:
        SilenceCreateSchema.model_validate(payload)
    except Exception as exc:
        assert "created_by" in str(exc)
    else:
        raise AssertionError("created_by must not be accepted from API clients")


def test_voice_callback_url_does_not_contain_global_secret():
    delivery = type("Delivery", (), {"id": 123})()

    url = build_voice_rule_callback_url(delivery)

    assert url.endswith("/api/integrations/voice/rule-callback/123")
    assert str(Config.VOICE_CALLBACK_SECRET) not in url
