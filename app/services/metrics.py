"""
Prometheus metric collectors for IncidentRelay.

Owns the shared CollectorRegistry and every collector the /metrics
endpoint serves (app/views/metrics_view.py). The module is a leaf on
purpose: the view imports it for the exposition, and services (alert
intake, the alert-group repo layer, the scheduler) import it to record
business events — so nothing here may import views or other services.

Counters are process-local: they count the events each process handles
itself. The web process serves /metrics, so its counters (HTTP intake,
manual creation, UI and chat actions) are the visible ones; scheduler
increments stay in the scheduler process.

The database-derived gauges (notification deliveries, failing
notification targets, scheduler heartbeat) are recomputed at scrape
time from the shared database, so they work across processes. Like the
readiness probe (app/services/readiness.py) they manage their own
connection and never raise: on a database outage the delivery gauges
are cleared and the heartbeat reads 0, with a warning in the logs.
"""

import logging
from datetime import timezone

from peewee import fn
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

from app.db import init_database
from app.modules.db.models import (
    AlertNotification,
    AppLock,
    UserNotificationDelivery,
)
from app.settings import Config
from app.version import get_service_version


logger = logging.getLogger("incidentrelay.metrics")

# A dedicated registry (instead of the global prometheus_client.REGISTRY)
# keeps the exposition limited to IncidentRelay's own metrics: the global
# one also exposes process collectors whose metric set differs between
# platforms and duplicates what runtime exporters already publish. The
# registry and the collectors are module-level singletons so repeated
# create_app() calls (tests, workers) cannot register them twice.
REGISTRY = CollectorRegistry()

HTTP_REQUESTS_TOTAL = Counter(
    "incidentrelay_http_requests",
    "HTTP requests handled by IncidentRelay.",
    labelnames=("method", "status"),
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "incidentrelay_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method",),
    registry=REGISTRY,
)

ALERTS_RECEIVED = Counter(
    "incidentrelay_alerts_received",
    "Alerts received through the integration API.",
    labelnames=("source",),
    registry=REGISTRY,
)

ALERT_GROUP_ACTIONS = Counter(
    "incidentrelay_alert_group_actions",
    "Alert group lifecycle transitions.",
    labelnames=("action",),
    registry=REGISTRY,
)

DATABASE_UP = Gauge(
    "incidentrelay_database_up",
    "1 when the database answered SELECT 1 at scrape time, else 0.",
    registry=REGISTRY,
)

MIGRATIONS_PENDING = Gauge(
    "incidentrelay_migrations_pending",
    "Number of on-disk migrations not yet applied.",
    registry=REGISTRY,
)

USER_NOTIFICATION_DELIVERIES = Gauge(
    "incidentrelay_user_notification_deliveries",
    "Recorded per-user notification deliveries by method and outcome.",
    labelnames=("method", "status"),
    registry=REGISTRY,
)

NOTIFICATION_TARGETS_FAILING = Gauge(
    "incidentrelay_notification_targets_failing",
    "Notification channels whose last delivery ended in an error.",
    labelnames=("provider",),
    registry=REGISTRY,
)

SCHEDULER_LAST_RUN = Gauge(
    "incidentrelay_scheduler_last_run_timestamp_seconds",
    "Unix time of the last scheduler heartbeat, 0 when it never ran.",
    registry=REGISTRY,
)

BUILD_INFO = Gauge(
    "incidentrelay_build_info",
    "Running IncidentRelay version, value is always 1.",
    labelnames=("version",),
    registry=REGISTRY,
)

BUILD_INFO.labels(version=get_service_version()).set(1)

# Lock name of the never-released row the scheduler refreshes as its
# heartbeat; app/services/scheduler.py writes it, the gauge reads it.
SCHEDULER_HEARTBEAT_LOCK_NAME = "scheduler_heartbeat"


def record_alert_received(source):
    """Count one alert accepted by the integration intake."""

    if not Config.METRICS_ENABLED:
        return

    ALERTS_RECEIVED.labels(source=str(source or "unknown")).inc()


def record_alert_group_action(action):
    """Count one alert group lifecycle transition."""

    if not Config.METRICS_ENABLED:
        return

    ALERT_GROUP_ACTIONS.labels(action=action).inc()


def refresh_notification_gauges():
    """
    Recompute the database-derived notification and heartbeat gauges.

    Opens its own connection and never raises: on failure the delivery
    gauges are cleared (absent from the exposition), the heartbeat reads
    0 and the reason is logged, so a scrape during a database outage
    still succeeds.
    """

    db = None
    db_was_closed = True

    try:
        db = init_database()
        db_was_closed = db.is_closed()

        if db_was_closed:
            db.connect(reuse_if_open=True)

        _refresh_delivery_gauges()
        _refresh_scheduler_heartbeat_gauge()
    except Exception as exc:
        USER_NOTIFICATION_DELIVERIES.clear()
        NOTIFICATION_TARGETS_FAILING.clear()
        SCHEDULER_LAST_RUN.set(0)
        logger.warning(
            "metrics notification gauge refresh failed",
            exc_info=exc,
        )
    finally:
        if db is not None and db_was_closed and not db.is_closed():
            try:
                db.close()
            except Exception:
                pass


def _refresh_delivery_gauges():
    """Map delivery and channel tables onto the gauges, replacing labels."""

    USER_NOTIFICATION_DELIVERIES.clear()
    NOTIFICATION_TARGETS_FAILING.clear()

    rows = (
        UserNotificationDelivery
        .select(
            UserNotificationDelivery.method,
            UserNotificationDelivery.status,
            fn.COUNT(UserNotificationDelivery.id).alias("total"),
        )
        .group_by(
            UserNotificationDelivery.method,
            UserNotificationDelivery.status,
        )
        .tuples()
    )

    for method, status, total in rows:
        USER_NOTIFICATION_DELIVERIES.labels(
            method=method,
            status=status,
        ).set(total)

    rows = (
        AlertNotification
        .select(
            AlertNotification.provider,
            fn.COUNT(AlertNotification.id).alias("total"),
        )
        .where(AlertNotification.last_error.is_null(False))
        .group_by(AlertNotification.provider)
        .tuples()
    )

    for provider, total in rows:
        NOTIFICATION_TARGETS_FAILING.labels(provider=provider).set(total)


def _refresh_scheduler_heartbeat_gauge():
    """Expose the heartbeat timestamp as unix time, 0 when absent."""

    lock = AppLock.get_or_none(
        AppLock.name == SCHEDULER_HEARTBEAT_LOCK_NAME,
    )

    if lock is None or lock.updated_at is None:
        SCHEDULER_LAST_RUN.set(0)
        return

    # Timestamps are stored as naive UTC values (app/modules/common.py).
    SCHEDULER_LAST_RUN.set(
        lock.updated_at.replace(tzinfo=timezone.utc).timestamp(),
    )
