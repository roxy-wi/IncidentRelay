import json
import logging
import os
import uuid
from datetime import datetime

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from app.settings import Config


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
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class EventOnlyFilter(logging.Filter):
    """
    Allow only audit actions, alert intake records and errors.

    This is a hard filter. Even if another module logs request records, they are
    not written to the configured JSON log file.
    """

    ALLOWED_LOGGERS = {
        "oncall.audit",
        "oncall.alerts",
        "oncall.error",
    }

    def filter(self, record):
        """
        Return True when a record should be written.
        """

        if record.levelno >= logging.ERROR:
            return True

        return record.name in self.ALLOWED_LOGGERS


def setup_json_logging(app):
    """
    Configure JSON file logging for the service.
    """

    log_file = Config.LOG_FILE
    log_dir = os.path.dirname(log_file)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handler = logging.FileHandler(log_file)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(EventOnlyFilter())

    level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Disable werkzeug request logs in the service log. Access logs should be
    # handled by a reverse proxy or process manager if needed.
    logging.getLogger("werkzeug").disabled = True

    app.logger.handlers.clear()
    app.logger.propagate = True
    app.logger.setLevel(level)

    register_error_handlers(app)


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
