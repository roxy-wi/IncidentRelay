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
business events without importing a view module; render_exposition()
there assembles the response. All database-derived gauges are evaluated
at scrape time and never raise, so the exposition keeps working while
the database is down, which is exactly when the gauges matter most.
In multiprocess deployments (PROMETHEUS_MULTIPROC_DIR set) the same
function merges the counter files of the IncidentRelay processes that
share the directory, i.e. one PID namespace: on a systemd host that is
the web workers plus the scheduler and the Telegram/Slack daemons, in
per-container deployments each container merges its own processes only.
"""

import hmac
import time
from typing import Union

from flask import Blueprint, Response, abort, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST

from app.services.metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    render_exposition,
)
from app.settings import Config


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


@metrics_bp.route(
    METRICS_PATH,
    methods=["GET"],
    provide_automatic_options=False,
)
def metrics() -> Union[Response, tuple]:
    """
    Serve the Prometheus exposition, or pretend the endpoint is absent.
    """

    if not Config.METRICS_ENABLED:
        abort(404)

    if not _authorized():
        return jsonify({"error": "Valid bearer token is required"}), 401

    return Response(
        render_exposition(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


@metrics_bp.route(
    METRICS_PATH,
    methods=["POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def metrics_wrong_method() -> Union[Response, tuple]:
    """
    Keep non-GET methods consistent with the disabled endpoint.

    Flask answers 405 or automatic OPTIONS during URL matching, before
    any view code runs, which would reveal that /metrics exists. This
    rule keeps every non-GET method answering 404 while disabled and
    405 when enabled. The 405 body is built here instead of raised, so
    the app-wide JSON error handler cannot drop the Allow header.
    """

    if not Config.METRICS_ENABLED:
        abort(404)

    return (
        jsonify({
            "error": "Method Not Allowed",
            "message": "The method is not allowed for the requested URL.",
            "status": 405,
        }),
        405,
        {"Allow": "GET"},
    )


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
