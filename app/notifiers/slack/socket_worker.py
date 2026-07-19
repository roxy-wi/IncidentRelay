"""Manage Slack Socket Mode clients for enabled notification channels."""

from dataclasses import dataclass
import hashlib
import logging
import threading

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse

from app.modules.db import channels_repo
from app.notifiers.slack.actions import (
    SlackActionError,
    handle_slack_socket_action,
)
from app.notifiers.types import SLACK_CHANNEL


logger = logging.getLogger("oncall.slack.socket")


@dataclass(frozen=True)
class SlackSocketConfig:
    key: str
    app_token: str
    channel_ids: tuple[int, ...]

    @property
    def fingerprint(self):
        return self.key


@dataclass
class SlackSocketConnection:
    config: SlackSocketConfig
    client: object


def _token_key(app_token):
    return hashlib.sha256(
        str(app_token).encode("utf-8")
    ).hexdigest()


def list_socket_configs():
    """Return one connection config per enabled Slack app token."""
    grouped = {}

    for channel in channels_repo.list_channels(enabled_only=True):
        if channel.channel_type != SLACK_CHANNEL:
            continue

        config = channel.config or {}
        if config.get("mode") != "bot_api":
            continue
        if str(config.get("connection_mode") or "http") != "socket_mode":
            continue

        app_token = str(config.get("app_token") or "").strip()
        if not app_token:
            continue

        key = _token_key(app_token)
        item = grouped.setdefault(
            key,
            {
                "app_token": app_token,
                "channel_ids": [],
            },
        )

        item["channel_ids"].append(channel.id)

    return {
        key: SlackSocketConfig(
            key=key,
            app_token=item["app_token"],
            channel_ids=tuple(sorted(item["channel_ids"])),
        )
        for key, item in grouped.items()
    }


class SlackSocketManager:
    """Reconcile long-lived Slack Socket Mode connections with DB config."""

    def __init__(self, app, client_factory=None):
        self.app = app
        self.client_factory = client_factory or self._create_client
        self.connections = {}
        self._lock = threading.RLock()

    def _create_client(self, config):
        client = SocketModeClient(
            app_token=config.app_token,
            auto_reconnect_enabled=True,
        )
        client.socket_mode_request_listeners.append(
            self._build_listener(config)
        )
        return client

    def _build_listener(self, config):
        def listener(client, request):
            if request.type != "interactive":
                client.send_socket_mode_response(
                    SocketModeResponse(envelope_id=request.envelope_id)
                )
                return

            # Slack expects an envelope acknowledgement before application work.
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=request.envelope_id)
            )

            payload = request.payload or {}
            if payload.get("type") != "block_actions":
                return

            try:
                with self.app.app_context():
                    result = handle_slack_socket_action(
                        payload=payload,
                        app_token=config.app_token,
                    )
                logger.info(
                    "Slack Socket Mode action processed",
                    extra={
                        "extra": {
                            "action": result.get("action"),
                            "alert_id": result.get("alert_id"),
                        }
                    },
                )
            except SlackActionError as exc:
                logger.warning(
                    "Slack Socket Mode action rejected",
                    extra={
                        "extra": {
                            "error": exc.error,
                            "status_code": exc.status_code,
                        }
                    },
                )
            except Exception:
                logger.exception("Slack Socket Mode action failed")

        return listener

    def reconcile(self):
        """Start, replace or stop clients to match enabled channel config."""
        desired = list_socket_configs()

        with self._lock:
            for key in list(self.connections):
                current = self.connections[key]
                wanted = desired.get(key)
                if wanted and wanted.fingerprint == current.config.fingerprint:
                    continue
                self._stop_connection(key)

            for key, config in desired.items():
                if key in self.connections:
                    continue
                self._start_connection(config)

        return len(self.connections)

    def _start_connection(self, config):
        client = self.client_factory(config)
        client.connect()
        self.connections[config.key] = SlackSocketConnection(
            config=config,
            client=client,
        )
        logger.info(
            "Slack Socket Mode connection started",
            extra={
                "extra": {
                    "app_token_fingerprint": config.key[:12],
                    "channel_count": len(config.channel_ids),
                }
            },
        )

    def _stop_connection(self, key):
        connection = self.connections.pop(key, None)
        if not connection:
            return
        try:
            connection.client.close()
        except Exception:
            logger.exception(
                "Slack Socket Mode connection close failed",
                extra={"extra": {"app_token_fingerprint": key[:12]}},
            )
        logger.info(
            "Slack Socket Mode connection stopped",
            extra={"extra": {"app_token_fingerprint": key[:12]}},
        )

    def close(self):
        with self._lock:
            for key in list(self.connections):
                self._stop_connection(key)
