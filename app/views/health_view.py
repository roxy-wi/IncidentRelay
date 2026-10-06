"""
Health probes, unauthenticated and outside the /api/ namespace so
load balancers can poll them without credentials.

/healthz is liveness and never touches the database, so an outage
cannot cause a pointless restart. /readyz is readiness: 503 until the
database answers and all migrations are applied.
"""

import logging
from typing import Any

from flask import Blueprint, jsonify

from app.services.readiness import run_readiness_probe


logger = logging.getLogger("oncall.health")

health_bp = Blueprint("health", __name__)


HEALTH_PATHS = ("/healthz", "/readyz")


@health_bp.route("/healthz", methods=["GET"])
def healthz():
    """Liveness probe: 200 as long as the process can respond."""
    return jsonify({"status": "ok"}), 200


@health_bp.route("/readyz", methods=["GET"])
def readyz():
    """
    Readiness probe: 503 until the database answers SELECT 1 and no
    migrations are pending. The shared probe in
    app/services/readiness.py does the checking.
    """

    response: dict[str, Any] = {"status": "ready"}
    http_status = 200

    probe = run_readiness_probe()

    if probe.database_error is not None:
        response["status"] = "not_ready"
        response["database"] = "error"
        response["database_error"] = "database check failed"
        logger.warning("readyz database check failed", exc_info=probe.database_error)
        return jsonify(response), 503

    response["database"] = "ok"

    if probe.migration_error is not None:
        response["status"] = "not_ready"
        response["migrations"] = {"error": "migration check failed"}
        http_status = 503
        logger.warning("readyz migration check failed", exc_info=probe.migration_error)
        return jsonify(response), http_status

    response["migrations"] = {
        "applied": probe.applied,
        "total": probe.total,
    }

    if probe.pending:
        response["status"] = "not_ready"
        response["migrations"]["pending"] = probe.pending
        http_status = 503

    return jsonify(response), http_status
