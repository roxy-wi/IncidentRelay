from flask import Blueprint, jsonify

from app.migrations.runner import migration_status
from app.version import get_service_version
from app.settings import Config


version_bp = Blueprint("version_api", __name__)


@version_bp.route("", methods=["GET"])
def get_version():
    """
    Return service version and migration status.
    """

    return jsonify({
        "service_version": get_service_version(),
        "migrations": migration_status(),
    })


@version_bp.route("/logging", methods=["GET"])
def logging_settings():
    """
    Return current logging settings.
    """

    return jsonify({
        "log_file": Config.LOG_FILE,
        "log_level": Config.LOG_LEVEL,
        "request_logging_registered": False,
        "allowed_loggers": ["oncall.audit", "oncall.alerts", "oncall.error"],
    })
