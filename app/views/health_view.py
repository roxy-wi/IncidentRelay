"""
Health probes for liveness and readiness checks.

The probes are deliberately unauthenticated and live outside the /api/
namespace so Kubernetes, HAProxy, nginx, AWS ELB and other load
balancers can poll them without credentials.

Conventions follow the Kubernetes naming style:

- /healthz: liveness. Returns 200 as long as the process can serve a
  request. Does NOT touch the database — a database outage must not
  cause Kubernetes to restart the pod, since a restart would not help.

- /readyz: readiness. Returns 200 only when the database is reachable
  and all on-disk migrations have been applied. Otherwise returns 503
  so the load balancer stops routing traffic until the process is
  fully usable.
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
    """
    Liveness probe. Returns 200 as long as the process can respond.
    Intentionally does not touch the database or any other dependency.
    """
    return jsonify({"status": "ok"}), 200


@health_bp.route("/readyz", methods=["GET"])
def readyz():
    """
    Readiness probe. Returns 200 only when:

    - the database connection can be opened and answers SELECT 1;
    - the number of applied migrations matches the number of migration
      files on disk (no pending migrations).

    Otherwise returns 503 with a structured payload describing what
    is not ready. The shared probe in app/services/readiness.py does
    the checking and never raises; this view only maps the result to
    the response payload.
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
