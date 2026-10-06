"""
Optional Prometheus /metrics endpoint in the Prometheus text format.

Disabled by default: without [metrics] enabled the endpoint answers
404 to every method. With auth_token set, scrapes must carry
"Authorization: Bearer <token>".
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
    Check the scrape against the configured token, empty means open.

    Compared as bytes: hmac.compare_digest rejects non-ASCII str, while
    headers and config values can legitimately contain them.
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
    """Serve the Prometheus exposition, or pretend the endpoint is absent."""

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

    Flask answers 405 or automatic OPTIONS during URL matching, which
    would reveal that /metrics exists. The body is built here so the
    app-wide JSON error handler cannot drop the Allow header.
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
    """Install the request-counting hooks, active only while enabled."""

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
