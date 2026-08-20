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

from app.db import init_database
from app.modules.db.migrations import (
    get_applied_migrations,
    get_migration_files,
)


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
    is not ready.
    """
    db = init_database()
    response: dict[str, Any] = {"status": "ready"}
    http_status = 200
    db_was_closed = db.is_closed()

    try:
        # Keep the connection open for both checks. Closing it after SELECT 1
        # and relying on an implicit reconnect in get_applied_migrations()
        # makes readiness depend on Peewee/backend autoconnect behaviour.
        try:
            if db_was_closed:
                db.connect(reuse_if_open=True)
            db.execute_sql("SELECT 1")
            response["database"] = "ok"
        except Exception:
            response["status"] = "not_ready"
            response["database"] = "error"
            response["database_error"] = "database check failed"
            logger.warning("readyz database check failed", exc_info=True)
            return jsonify(response), 503

        # Migration table stores names WITHOUT the .py suffix; on-disk files
        # carry it. Normalize the disk side so set comparison works (this
        # matches how migrations.migrate() itself compares them).
        try:
            applied = set(get_applied_migrations())
            on_disk = [
                filename.replace(".py", "")
                for filename in get_migration_files()
            ]
            pending = [name for name in on_disk if name not in applied]

            response["migrations"] = {
                "applied": len(applied),
                "total": len(on_disk),
            }

            if pending:
                response["status"] = "not_ready"
                response["migrations"]["pending"] = pending
                http_status = 503
        except Exception:
            response["status"] = "not_ready"
            response["migrations"] = {"error": "migration check failed"}
            http_status = 503
            logger.warning("readyz migration check failed", exc_info=True)

        return jsonify(response), http_status
    finally:
        if db_was_closed and not db.is_closed():
            try:
                db.close()
            except Exception:
                pass
