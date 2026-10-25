"""Voice notification callbacks must use AlertGroup IDs and the called user."""
from types import SimpleNamespace

from app.views import integrations_view as voice_api


def _delivery(*, authorized=True):
    group = SimpleNamespace(id=61, team_id=9)
    user = SimpleNamespace(id=12, active=authorized, deleted=False)
    delivery = SimpleNamespace(
        id=8,
        group=group,
        user=user,
        method="voice_call",
        provider_status=None,
        provider_payload=None,
        updated_at=None,
        save=lambda: None,
    )
    return delivery


def _event(*, action="acknowledge", digit=None):
    return SimpleNamespace(
        call_id="call-1", status="completed", raw={},
        action=action, digit=digit, event_type="keypress",
    )


def test_voice_ack_uses_alert_group_and_delivery_recipient(monkeypatch):
    delivery = _delivery()
    events = []
    calls = []
    monkeypatch.setattr(voice_api, "can_respond_team", lambda user, team: user.id == 12 and team == 9)
    monkeypatch.setattr(voice_api.alerts_repo, "create_alert_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(voice_api, "acknowledge_alert", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = voice_api._process_voice_rule_callback_event(delivery, _event())

    assert calls == [((61,), {"user_id": 12, "source": "voice"})]
    assert events[0]["group_id"] == 61
    assert events[0]["user_id"] == 12
    assert result["alert_group_id"] == 61
    assert result["action"] == "acknowledge"
    assert result["action_rejected"] is False


def test_voice_digit_resolve_uses_same_actor_and_action_contract(monkeypatch):
    delivery = _delivery()
    calls = []
    monkeypatch.setattr(voice_api, "can_respond_team", lambda user, team: True)
    monkeypatch.setattr(voice_api.alerts_repo, "create_alert_event", lambda **kwargs: None)
    monkeypatch.setattr(voice_api, "resolve_alert", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = voice_api._process_voice_rule_callback_event(delivery, _event(action=None, digit="2"))
    assert calls == [((61,), {"user_id": 12, "source": "voice"})]
    assert result["action"] == "resolve"


def test_voice_callback_cannot_execute_action_without_responder_permission(monkeypatch):
    delivery = _delivery()
    calls = []
    monkeypatch.setattr(voice_api, "can_respond_team", lambda user, team: False)
    monkeypatch.setattr(voice_api.alerts_repo, "create_alert_event", lambda **kwargs: None)
    monkeypatch.setattr(voice_api, "acknowledge_alert", lambda *args, **kwargs: calls.append((args, kwargs)))
    result = voice_api._process_voice_rule_callback_event(delivery, _event())

    assert calls == []
    assert result["action"] is None
    assert result["action_rejected"] is True


def test_voice_endpoint_rejects_callback_for_non_voice_delivery(client, monkeypatch):
    from app.settings import Config

    monkeypatch.setattr(Config, "VOICE_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        voice_api.UserNotificationDelivery,
        "get_or_none",
        lambda *args, **kwargs: SimpleNamespace(id=8, method="browser_push"),
    )
    monkeypatch.setattr(
        voice_api,
        "create_voice_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not parse a callback for the wrong delivery method")
        ),
    )

    response = client.post(
        "/api/integrations/voice/rule-callback/8",
        json={"event": "keypress"},
        headers={"X-IncidentRelay-Callback-Secret": "callback-secret"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "delivery is not a voice call"
