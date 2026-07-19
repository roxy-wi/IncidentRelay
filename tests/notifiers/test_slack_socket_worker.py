from types import SimpleNamespace

from app.notifiers.slack import socket_worker


class FakeClient:
    def __init__(self):
        self.connected = False
        self.closed = False

    def connect(self):
        self.connected = True

    def close(self):
        self.closed = True


def make_channel(channel_id, app_token, bot_token="xoxb-token"):
    return SimpleNamespace(
        id=channel_id,
        channel_type="slack",
        config={
            "mode": "bot_api",
            "connection_mode": "socket_mode",
            "app_token": app_token,
            "bot_token": bot_token,
        },
    )


def test_socket_configs_deduplicate_shared_app_token(monkeypatch):
    monkeypatch.setattr(
        socket_worker.channels_repo,
        "list_channels",
        lambda enabled_only=True: [
            make_channel(1, "xapp-shared"),
            make_channel(2, "xapp-shared"),
        ],
    )

    configs = socket_worker.list_socket_configs()
    assert len(configs) == 1
    config = next(iter(configs.values()))
    assert config.channel_ids == (1, 2)


def test_socket_manager_reconcile_is_idempotent(monkeypatch):
    state = {
        "configs": {
            "key": socket_worker.SlackSocketConfig(
                key="key",
                app_token="xapp-token",
                channel_ids=(1,),
            )
        }
    }
    monkeypatch.setattr(
        socket_worker,
        "list_socket_configs",
        lambda: state["configs"],
    )
    clients = []

    def factory(config):
        client = FakeClient()
        clients.append(client)
        return client

    manager = socket_worker.SlackSocketManager(
        SimpleNamespace(),
        client_factory=factory,
    )

    assert manager.reconcile() == 1
    assert manager.reconcile() == 1
    assert len(clients) == 1
    assert clients[0].connected is True

    state["configs"] = {}
    assert manager.reconcile() == 0
    assert clients[0].closed is True


def test_socket_listener_acknowledges_before_processing(app, monkeypatch):
    config = socket_worker.SlackSocketConfig(
        key="key",
        app_token="xapp-token",
        channel_ids=(1,),
    )
    manager = socket_worker.SlackSocketManager(app)
    order = []

    class ListenerClient:
        def send_socket_mode_response(self, response):
            assert response.envelope_id == "envelope-1"
            order.append("ack")

    def fake_handle(**kwargs):
        assert order == ["ack"]
        order.append("process")
        return {
            "action": "acknowledge",
            "alert_id": 123,
        }

    monkeypatch.setattr(
        socket_worker,
        "handle_slack_socket_action",
        fake_handle,
    )

    listener = manager._build_listener(config)
    listener(
        ListenerClient(),
        SimpleNamespace(
            type="interactive",
            envelope_id="envelope-1",
            payload={
                "type": "block_actions",
            },
        ),
    )

    assert order == ["ack", "process"]
