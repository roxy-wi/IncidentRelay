from types import SimpleNamespace

import pytest

from app.notifiers.lark.notifier import LarkNotifier


class FakeResponse:
    def __init__(self, payload=None, json_error=None):
        self.payload = payload
        self.json_error = json_error
        self.status_checked = False

    def raise_for_status(self):
        self.status_checked = True

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def make_channel(config):
    return SimpleNamespace(config=config)


def test_lark_sends_unsigned_text_message(monkeypatch):
    response = FakeResponse({"code": 0, "msg": "success"})
    calls = []

    def fake_safe_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return response

    monkeypatch.setattr(
        "app.notifiers.lark.notifier.safe_request",
        fake_safe_request,
    )

    result = LarkNotifier().send(
        make_channel({
            "webhook_url": (
                "https://open.feishu.cn/open-apis/bot/v2/hook/test"
            ),
        }),
        SimpleNamespace(),
        "Alert text",
    )

    assert calls == [{
        "method": "POST",
        "url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        "json": {
            "msg_type": "text",
            "content": {"text": "Alert text"},
        },
        "timeout": 10,
    }]
    assert response.status_checked is True
    assert result == {"provider": "lark"}


def test_lark_sends_signed_text_message(monkeypatch):
    response = FakeResponse({
        "StatusCode": 0,
        "StatusMessage": "success",
    })
    captured = {}

    monkeypatch.setattr(
        "app.notifiers.lark.notifier.time.time",
        lambda: 1_700_000_000,
    )

    def fake_safe_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return response

    monkeypatch.setattr(
        "app.notifiers.lark.notifier.safe_request",
        fake_safe_request,
    )

    LarkNotifier().send(
        make_channel({
            "webhook_url": (
                "https://open.larksuite.com/open-apis/bot/v2/hook/test"
            ),
            "signing_secret": "test-secret",
        }),
        SimpleNamespace(),
        "Alert text",
    )

    assert captured["json"] == {
        "msg_type": "text",
        "content": {"text": "Alert text"},
        "timestamp": "1700000000",
        "sign": "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84=",
    }


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"code": 19021, "msg": "sign match fail"}, "sign match fail"),
        (
            {"StatusCode": 1, "StatusMessage": "invalid request"},
            "invalid request",
        ),
    ],
)
def test_lark_rejects_provider_application_errors(
    monkeypatch,
    payload,
    message,
):
    monkeypatch.setattr(
        "app.notifiers.lark.notifier.safe_request",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    with pytest.raises(RuntimeError, match=message):
        LarkNotifier().send(
            make_channel({"webhook_url": "https://example.test/hook"}),
            SimpleNamespace(),
            "Alert text",
        )


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(json_error=ValueError("not json")),
        FakeResponse({"unexpected": "response"}),
        FakeResponse([]),
    ],
)
def test_lark_rejects_invalid_provider_responses(monkeypatch, response):
    monkeypatch.setattr(
        "app.notifiers.lark.notifier.safe_request",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(RuntimeError, match="invalid"):
        LarkNotifier().send(
            make_channel({"webhook_url": "https://example.test/hook"}),
            SimpleNamespace(),
            "Alert text",
        )


def test_lark_requires_webhook_url():
    with pytest.raises(RuntimeError, match="webhook_url is missing"):
        LarkNotifier().send(
            make_channel({}),
            SimpleNamespace(),
            "Alert text",
        )
