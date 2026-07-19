import json
import logging
import os
import uuid
from datetime import datetime

from flask import jsonify, request
from werkzeug.exceptions import HTTPException
from peewee import DoesNotExist

from app.services.incidents import responders
from app.settings import Config
from app.modules.redaction import redact_secrets


class JsonFormatter(logging.Formatter):
    """
    Format log records as JSON lines.
    """

    def format(self, record):
        """
        Convert a log record to a JSON string.
        """

        payload = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        extra = getattr(record, "extra", None)

        if isinstance(extra, dict):
            payload.update(extra)

        if record.exc_info:
            payload["exception"] = redact_secrets(self.formatException(record.exc_info))

        return json.dumps(redact_secrets(payload), ensure_ascii=False)


LOG_ROLE_APP = "app"
LOG_ROLE_SCHEDULER = "scheduler"
LOG_ROLE_TELEGRAM = "telegram"
LOG_ROLE_SLACK = "slack"


class EventOnlyFilter(logging.Filter):
    """Allow only role-specific operational logs."""

    def __init__(self, log_role=LOG_ROLE_APP):
        super().__init__()
        self.log_role = _normalize_log_role(log_role)
        self.allowed_loggers = _allowed_loggers_for_role(self.log_role)

    def filter(self, record):
        """Return True when a record should be written."""
        if record.name in self.allowed_loggers:
            return True

        # Keep non-role errors out of app log when they belong to workers.
        if record.levelno >= logging.ERROR:
            if self.log_role == LOG_ROLE_APP and record.name in {
                "oncall.scheduler",
                "oncall.telegram",
                "oncall.slack",
                "oncall.slack.socket",
            }:
                return False

            return True

        return False


def _normalize_log_role(log_role=None):
    """Return normalized runtime log role."""
    value = (
        log_role
        or os.environ.get("INCIDENTRELAY_LOG_ROLE")
        or os.environ.get("INCEDENTRELAY_LOG_ROLE")
        or LOG_ROLE_APP
    )

    value = str(value).strip().lower().replace("_", "-")

    if value in {"web", "main", "api", "flask"}:
        return LOG_ROLE_APP

    if value in {"scheduler", "worker-scheduler"}:
        return LOG_ROLE_SCHEDULER

    if value in {"telegram", "telegram-worker", "telegram_worker"}:
        return LOG_ROLE_TELEGRAM

    if value in {"slack", "slack-worker", "slack_worker", "socket-mode"}:
        return LOG_ROLE_SLACK

    return LOG_ROLE_APP


def _log_file_for_role(log_role):
    """Return log file path for runtime role."""
    if log_role == LOG_ROLE_SCHEDULER:
        return Config.LOG_SCHEDULER_FILE

    if log_role == LOG_ROLE_TELEGRAM:
        return Config.LOG_TELEGRAM_WORKER_FILE

    if log_role == LOG_ROLE_SLACK:
        return Config.LOG_SLACK_WORKER_FILE

    return Config.LOG_APP_FILE


def _allowed_loggers_for_role(log_role):
    """
    Return allowed logger names for runtime role.

    The role filter keeps process logs isolated even when modules share
    logger names.
    """
    if log_role == LOG_ROLE_SCHEDULER:
        return {
            "oncall.scheduler",
            "oncall.alerts",
            "oncall.notifications",
            "oncall.voice",
            "oncall.error",
            "shift_notifications"
        }

    if log_role == LOG_ROLE_TELEGRAM:
        return {
            "oncall.telegram",
            "oncall.error",
        }

    if log_role == LOG_ROLE_SLACK:
        return {
            "oncall.slack",
            "oncall.slack.socket",
            "oncall.error",
        }

    return {
        "oncall.audit",
        "oncall.alerts",
        "oncall.error",
        "oncall.notifications",
        "oncall.voice",
        "oncall.incidents",
    }


def setup_json_logging(app=None, log_role=None):
    """Configure JSON file logging for one runtime role."""
    role = _normalize_log_role(log_role)
    log_file = _log_file_for_role(role)

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handler = logging.FileHandler(log_file)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(EventOnlyFilter(role))

    level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Avoid duplicate stdout/stderr logs from basicConfig or Werkzeug.
    logging.getLogger("werkzeug").disabled = True

    if app is not None:
        responders.logger.handlers.clear()
        responders.logger.propagate = True
        responders.logger.setLevel(level)
        register_error_handlers(app)

    logging.getLogger("oncall.error").info(
        "json logging configured",
        extra={
            "extra": {
                "event_type": "logging",
                "log_role": role,
                "log_file": log_file,
            }
        },
    )


def register_error_handlers(app):
    """
    Add error logs only. Do not register request logging hooks.
    """

    @app.errorhandler(HTTPException)
    def log_http_exception(error):
        """
        Log only server-side HTTP exceptions.
        """

        if error.code and error.code >= 500:
            logging.getLogger("oncall.error").error(
                "http exception",
                extra={
                    "extra": {
                        "event_type": "error",
                        "method": request.method,
                        "path": request.path,
                        "status": error.code,
                        "error": error.name,
                        "description": error.description,
                        "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
                    }
                },
            )

        return jsonify({
            "error": error.name,
            "message": error.description,
            "status": error.code,
        }), error.code

    @app.errorhandler(DoesNotExist)
    def handle_model_not_found(error):
        """
        Return 404 for missing database objects instead of logging them as 500.

        Peewee DoesNotExist often means that the requested resource was deleted,
        hidden by soft-delete filters, or never existed. This is a normal API
        404 case, not an unhandled server error.
        """
        return jsonify({
            "error": "not_found",
            "message": "Requested resource was not found.",
            "status": 404,
        }), 404

    @app.errorhandler(Exception)
    def log_unhandled_exception(error):
        """
        Log unhandled exceptions as JSON and return a stable 500 response.
        """

        error_id = str(uuid.uuid4())

        logging.getLogger("oncall.error").error(
            "unhandled exception",
            exc_info=(type(error), error, error.__traceback__),
            extra={
                "extra": {
                    "event_type": "error",
                    "error_id": error_id,
                    "method": request.method,
                    "path": request.path,
                    "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
                }
            },
        )

        return jsonify({
            "error": "Internal Server Error",
            "error_id": error_id,
            "message": "Unexpected server error. Check JSON log by error_id.",
        }), 500
