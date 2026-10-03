"""
Optional Prometheus metrics endpoint.

Exposes GET /metrics in the Prometheus text exposition format using the
official prometheus_client package. The endpoint follows the health
probe conventions (it lives outside the /api/ namespace) but is
disabled by default:

- [metrics] enabled = true   -> the endpoint serves the exposition;
- otherwise                  -> the endpoint answers 404 and does not
  exist for scrapers, scanners or proxies.

Scraping is optionally protected by a bearer token:

- [metrics] auth_token empty -> unauthenticated scraping, the same
  trust model as /healthz (protect the port at the network layer);
- auth_token set             -> requests must carry
  "Authorization: Bearer <token>" or receive 401. The comparison is
  constant-time over bytes so the endpoint does not become a timing
  oracle and a non-ASCII header cannot crash it.

The collectors live in app/services/metrics.py so services can record
business events without importing a view module. The database,
migration, notification and heartbeat gauges are evaluated at scrape
time. The database checks share the readiness probe with /readyz
(app/services/readiness.py) and never raise, so the exposition keeps
working while the database is down, which is exactly when the gauges
matter most.
"""

import hmac
import logging
import time
from typing import Union

from flask import Blueprint, Response, abort, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.services.metrics import (
    DATABASE_UP,
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    MIGRATIONS_PENDING,
    REGISTRY,
    refresh_notification_gauges,
)
from app.services.readiness import run_readiness_probe
from app.settings import Config


logger = logging.getLogger("incidentrelay.metrics")

metrics_bp = Blueprint("metrics", __name__)

METRICS_PATH = "/metrics"


def _authorized():
    """
    Check scrape authorization against the configured token.

    An empty configured token means the endpoint is intentionally open
    (the /healthz trust model). A configured token must match the
    Authorization header exactly. Both sides are compared as bytes:
    hmac.compare_digest rejects non-ASCII str arguments, and headers
    and config files can legitimately contain non-ASCII values. The
    import is lazy because app.services.integrations.auth pulls in the
    whole API middleware stack and metrics_view is imported from
    create_app().
    """

    expected = (Config.METRICS_AUTH_TOKEN or "").strip()

    if not expected:
        return True

    from app.services.integrations.auth import get_bearer_token

    provided = get_bearer_token()

    if provided is None:
        return False

    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


def _update_database_gauges():
    """
    Refresh database_up and migrations_pending at scrape time.

    Maps the shared readiness probe result onto the gauges. Every
    failure path only degrades the gauges and logs a warning; the
    exposition itself never fails.
    """

    probe = run_readiness_probe()

    if probe.database_error is not None:
        DATABASE_UP.set(0)
        MIGRATIONS_PENDING.set(0)
        logger.warning(
            "metrics database check failed",
            exc_info=probe.database_error,
        )
        return

    DATABASE_UP.set(1)

    if probe.migration_error is not None:
        # The database answers but the migration state is unknown.
        # Report no pending migrations: /readyz is the authoritative
        # readiness signal.
        MIGRATIONS_PENDING.set(0)
        logger.warning(
            "metrics migration check failed",
            exc_info=probe.migration_error,
        )
        return

    MIGRATIONS_PENDING.set(len(probe.pending))


@metrics_bp.route(METRICS_PATH, methods=["GET"])
def metrics() -> Union[Response, tuple]:
    """
    Serve the Prometheus exposition, or pretend the endpoint is absent.
    """

    if not Config.METRICS_ENABLED:
        abort(404)

    if not _authorized():
        return jsonify({"error": "Valid bearer token is required"}), 401

    _update_database_gauges()
    refresh_notification_gauges()

    return Response(
        generate_latest(REGISTRY),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


@metrics_bp.route(METRICS_PATH, methods=["POST", "PUT", "PATCH", "DELETE"])
def metrics_wrong_method() -> Union[Response, tuple]:
    """
    Keep non-GET methods consistent with the disabled endpoint.

    The GET rule 404s from inside the view when metrics are disabled,
    but Flask answers 405 for other methods during URL matching — before
    any view code runs — which would reveal that /metrics exists. This
    rule keeps every method answering 404 while disabled; when enabled,
    non-GET methods keep the regular 405.
    """

    if not Config.METRICS_ENABLED:
        abort(404)

    abort(405)


def register_http_metrics(flask_app) -> None:
    """
    Install the app-level request-counting hooks.

    Counting only happens while METRICS_ENABLED is true, so deployments
    that never enable the endpoint pay no per-request cost.
    """

    @flask_app.before_request
    def metrics_before_request():
        """Record the request start time for the latency histogram."""
        if Config.METRICS_ENABLED:
            g.metrics_request_started = time.monotonic()

    @flask_app.after_request
    def metrics_after_request(response):
        """Count the handled request and observe its duration."""
        if not Config.METRICS_ENABLED:
            return response

        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            status=str(response.status_code),
        ).inc()

        started = getattr(g, "metrics_request_started", None)

        if started is not None:
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method,
            ).observe(time.monotonic() - started)

        return response
