from types import SimpleNamespace
import json
import logging

from app.notifiers.slack import socket_worker
from app.modules.logger import (
    EventOnlyFilter,
    LOG_ROLE_SLACK,
    _log_file_for_role,
    _normalize_log_role,
    setup_json_logging,
)
from app.settings import Config


def _record(name, level=logging.INFO):
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg="test",
        args=(),
        exc_info=None,
    )


def test_slack_log_role_aliases_and_file(monkeypatch, tmp_path):
    log_file = tmp_path / "incidentrelay-slack-worker.log"
    monkeypatch.setattr(Config, "LOG_SLACK_WORKER_FILE", str(log_file))

    assert _normalize_log_role("slack") == LOG_ROLE_SLACK
    assert _normalize_log_role("slack-worker") == LOG_ROLE_SLACK
    assert _normalize_log_role("socket-mode") == LOG_ROLE_SLACK
    assert _log_file_for_role(LOG_ROLE_SLACK) == str(log_file)


def test_slack_role_filter_isolates_worker_events():
    role_filter = EventOnlyFilter(LOG_ROLE_SLACK)

    assert role_filter.filter(_record("oncall.slack")) is True
    assert role_filter.filter(_record("oncall.slack.socket")) is True
    assert role_filter.filter(_record("oncall.error", logging.ERROR)) is True
    assert role_filter.filter(_record("oncall.scheduler")) is False
    assert role_filter.filter(_record("oncall.telegram")) is False


def test_slack_role_writes_json_to_separate_file(monkeypatch, tmp_path):
    log_file = tmp_path / "incidentrelay-slack-worker.log"
    monkeypatch.setattr(Config, "LOG_SLACK_WORKER_FILE", str(log_file))
    monkeypatch.setattr(Config, "LOG_LEVEL", "INFO")

    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    werkzeug = logging.getLogger("werkzeug")
    old_werkzeug_disabled = werkzeug.disabled

    try:
        setup_json_logging(log_role="slack")
        logging.getLogger("oncall.slack").info("Slack worker test event")
        logging.getLogger("oncall.slack.socket").warning("Slack socket test event")
        logging.getLogger("oncall.scheduler").info("must not be written")

        for handler in root.handlers:
            handler.flush()
    finally:
        current_handlers = list(root.handlers)
        root.handlers.clear()
        for handler in current_handlers:
            handler.close()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)
        werkzeug.disabled = old_werkzeug_disabled

    records = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    logger_names = {record["logger"] for record in records}

    assert "oncall.slack" in logger_names
    assert "oncall.slack.socket" in logger_names
    assert "oncall.scheduler" not in logger_names
    assert any(
        record.get("log_role") == "slack"
        and record.get("log_file") == str(log_file)
        for record in records
    )



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
