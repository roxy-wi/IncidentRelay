import fcntl
import logging
import os
import re
import socket
import time
from contextlib import contextmanager
from datetime import timedelta, timezone

from peewee import fn
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.multiprocess import (
    MultiProcessCollector,
    mark_process_dead,
)
from prometheus_client.registry import Collector

from app.db import init_database
from app.modules.common import utc_now
from app.modules.db.locks_repo import touch_lock
from app.modules.db.models import (
    AlertNotification,
    AppLock,
    PendingOrchestratedEvent,
    UserNotificationDelivery,
)
from app.services.readiness import run_readiness_probe
from app.settings import Config
from app.version import get_service_version


logger = logging.getLogger("incidentrelay.metrics")

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

WORKER_HEARTBEAT_LOCK_NAMES = {
    "scheduler": "scheduler_heartbeat",
    "telegram": "telegram_worker_heartbeat",
    "slack": "slack_worker_heartbeat",
}

# Keep the existing scheduler metric/lock name for backwards compatibility.
SCHEDULER_HEARTBEAT_LOCK_NAME = WORKER_HEARTBEAT_LOCK_NAMES["scheduler"]
WORKER_HEARTBEAT_MIN_INTERVAL_SECONDS = 15
_WORKER_HEARTBEAT_LAST_ATTEMPT = {}

# Window of the *_recent database gauges, filtered by updated_at:
# delivery rows transition in place, so created_at misses late failures.
RECENT_WINDOW = timedelta(hours=24)


def multiprocess_dir():
    """Return the configured multiprocess directory, or None."""

    return (
        os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        or os.environ.get("prometheus_multiproc_dir")
        or None
    )


def is_multiprocess_enabled():
    """True when counters are backed by the multiprocess directory."""

    return multiprocess_dir() is not None


# Frozen at import: prometheus_client picks its value class from the
# same environment, so the process model cannot change at runtime.
_MULTIPROC_DIR = multiprocess_dir()


class DatabaseGaugeCollector(Collector):
    def collect(self):
        yield from self._database_gauges()
        yield from self._operational_gauges()
        yield self._build_info_gauge()

    def _database_gauges(self):
        database_up = GaugeMetricFamily(
            "incidentrelay_database_up",
            "1 when the database answered SELECT 1 at scrape time, else 0.",
        )
        migrations_pending = GaugeMetricFamily(
            "incidentrelay_migrations_pending",
            "Number of on-disk migrations not yet applied.",
        )

        probe = run_readiness_probe()

        if probe.database_error is not None:
            database_up.add_metric([], 0)
            logger.warning(
                "metrics database check failed",
                exc_info=probe.database_error,
            )
            yield database_up
            return

        database_up.add_metric([], 1)

        if probe.migration_error is not None:
            logger.warning(
                "metrics migration check failed",
                exc_info=probe.migration_error,
            )
            yield database_up
            return

        migrations_pending.add_metric([], len(probe.pending))
        yield database_up
        yield migrations_pending

    def _operational_gauges(self):
        deliveries = GaugeMetricFamily(
            "incidentrelay_user_notification_deliveries_recent",
            "User notification deliveries updated in the last 24 hours, "
            "by method and outcome.",
            labels=("method", "status"),
        )
        errors = GaugeMetricFamily(
            "incidentrelay_alert_notification_errors_recent",
            "Alert notification deliveries that ended in an error, "
            "updated in the last 24 hours.",
            labels=("provider",),
        )
        scheduler_heartbeat = GaugeMetricFamily(
            "incidentrelay_scheduler_last_run_timestamp_seconds",
            "Unix time of the last scheduler heartbeat, 0 when it never ran.",
        )
        worker_heartbeat = GaugeMetricFamily(
            "incidentrelay_worker_last_seen_timestamp_seconds",
            "Unix time of the last successful worker-loop heartbeat.",
            labels=("worker",),
        )
        notification_queue_depth = GaugeMetricFamily(
            "incidentrelay_user_notification_queue_depth",
            "User notification work that is due or currently processing.",
            labels=("state",),
        )
        notification_queue_oldest_age = GaugeMetricFamily(
            "incidentrelay_user_notification_queue_oldest_age_seconds",
            "Age in seconds of the oldest user notification work item.",
            labels=("state",),
        )
        orchestration_pending = GaugeMetricFamily(
            "incidentrelay_orchestration_pending_events",
            "Paused orchestration events by current status.",
            labels=("status",),
        )
        orchestration_oldest_due_age = GaugeMetricFamily(
            "incidentrelay_orchestration_oldest_due_age_seconds",
            "Age in seconds of the oldest paused orchestration event that is due.",
        )

        db = None
        db_was_closed = True
        now = utc_now()
        delivery_rows = []
        error_rows = []
        due_delivery_count = None
        due_delivery_oldest = None
        processing_delivery_count = None
        processing_delivery_oldest = None
        orchestration_rows = None
        orchestration_oldest_due = None
        heartbeat_values = {}

        try:
            db = init_database()
            db_was_closed = db.is_closed()

            if db_was_closed:
                db.connect(reuse_if_open=True)

            # Windowed on updated_at so a scrape never scans the full
            # delivery history and late failures of old rows still count.
            recent_since = now - RECENT_WINDOW

            delivery_rows = list(
                UserNotificationDelivery
                .select(
                    UserNotificationDelivery.method,
                    UserNotificationDelivery.status,
                    fn.COUNT(UserNotificationDelivery.id).alias("total"),
                )
                .where(UserNotificationDelivery.updated_at >= recent_since)
                .group_by(
                    UserNotificationDelivery.method,
                    UserNotificationDelivery.status,
                )
                .tuples()
            )

            error_rows = list(
                AlertNotification
                .select(
                    AlertNotification.provider,
                    fn.COUNT(AlertNotification.id).alias("total"),
                )
                .where(
                    AlertNotification.last_error.is_null(False),
                    AlertNotification.updated_at >= recent_since,
                )
                .group_by(AlertNotification.provider)
                .tuples()
            )

            due_delivery_query = UserNotificationDelivery.select().where(
                (UserNotificationDelivery.status == "pending")
                & (UserNotificationDelivery.scheduled_at <= now)
            )
            due_delivery_count = due_delivery_query.count()
            due_delivery = (
                due_delivery_query
                .order_by(UserNotificationDelivery.scheduled_at.asc())
                .first()
            )
            if due_delivery is not None:
                due_delivery_oldest = due_delivery.scheduled_at

            processing_delivery_query = UserNotificationDelivery.select().where(
                UserNotificationDelivery.status == "processing"
            )
            processing_delivery_count = processing_delivery_query.count()
            processing_delivery = (
                processing_delivery_query
                .order_by(UserNotificationDelivery.updated_at.asc())
                .first()
            )
            if processing_delivery is not None:
                processing_delivery_oldest = processing_delivery.updated_at

            orchestration_rows = list(
                PendingOrchestratedEvent
                .select(
                    PendingOrchestratedEvent.status,
                    fn.COUNT(PendingOrchestratedEvent.id).alias("total"),
                )
                .where(
                    PendingOrchestratedEvent.status.in_(
                        ("pending", "activating", "failed")
                    )
                )
                .group_by(PendingOrchestratedEvent.status)
                .tuples()
            )

            due_orchestration = (
                PendingOrchestratedEvent
                .select()
                .where(
                    (PendingOrchestratedEvent.status == "pending")
                    & (PendingOrchestratedEvent.activation_at <= now)
                    & (
                        PendingOrchestratedEvent.next_attempt_at.is_null(True)
                        | (PendingOrchestratedEvent.next_attempt_at <= now)
                    )
                )
                .order_by(
                    fn.COALESCE(
                        PendingOrchestratedEvent.next_attempt_at,
                        PendingOrchestratedEvent.activation_at,
                    ).asc(),
                    PendingOrchestratedEvent.id.asc(),
                )
                .first()
            )
            if due_orchestration is not None:
                orchestration_oldest_due = (
                    due_orchestration.next_attempt_at
                    or due_orchestration.activation_at
                )

            heartbeat_rows = (
                AppLock
                .select(AppLock.name, AppLock.updated_at)
                .where(
                    AppLock.name.in_(
                        tuple(WORKER_HEARTBEAT_LOCK_NAMES.values())
                    )
                )
                .tuples()
            )
            heartbeat_values = {
                name: self._timestamp(updated_at)
                for name, updated_at in heartbeat_rows
                if updated_at is not None
            }
        except Exception as exc:
            delivery_rows = []
            error_rows = []
            due_delivery_count = None
            processing_delivery_count = None
            orchestration_rows = None
            heartbeat_values = {}
            logger.warning(
                "metrics operational gauge refresh failed",
                exc_info=exc,
            )
        finally:
            if db is not None and db_was_closed and not db.is_closed():
                try:
                    db.close()
                except Exception:
                    pass

        for method, status, total in delivery_rows:
            deliveries.add_metric(
                (method, status),
                total,
            )

        for provider, total in error_rows:
            errors.add_metric((provider,), total)

        if due_delivery_count is not None:
            notification_queue_depth.add_metric(
                ("due",),
                due_delivery_count,
            )
            notification_queue_depth.add_metric(
                ("processing",),
                processing_delivery_count or 0,
            )
            notification_queue_oldest_age.add_metric(
                ("due",),
                self._age_seconds(now, due_delivery_oldest),
            )
            notification_queue_oldest_age.add_metric(
                ("processing",),
                self._age_seconds(now, processing_delivery_oldest),
            )

        if orchestration_rows is not None:
            orchestration_counts = {
                status: int(total or 0)
                for status, total in orchestration_rows
            }
            for status in ("pending", "activating", "failed"):
                orchestration_pending.add_metric(
                    (status,),
                    orchestration_counts.get(status, 0),
                )
            orchestration_oldest_due_age.add_metric(
                [],
                self._age_seconds(now, orchestration_oldest_due),
            )

        for worker, lock_name in WORKER_HEARTBEAT_LOCK_NAMES.items():
            worker_heartbeat.add_metric(
                (worker,),
                heartbeat_values.get(lock_name, 0),
            )

        scheduler_heartbeat.add_metric(
            [],
            heartbeat_values.get(SCHEDULER_HEARTBEAT_LOCK_NAME, 0),
        )

        yield deliveries
        yield errors
        yield notification_queue_depth
        yield notification_queue_oldest_age
        yield orchestration_pending
        yield orchestration_oldest_due_age
        yield worker_heartbeat
        yield scheduler_heartbeat

    @staticmethod
    def _age_seconds(now, value):
        if value is None:
            return 0
        return max(0.0, (now - value).total_seconds())

    @staticmethod
    def _timestamp(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    def _build_info_gauge(self):
        """Report the running version once, whatever the process count."""

        build_info = GaugeMetricFamily(
            "incidentrelay_build_info",
            "Running IncidentRelay version, value is always 1.",
            labels=("version",),
        )
        build_info.add_metric(
            (get_service_version(),),
            1,
        )
        return build_info


DATABASE_GAUGES = DatabaseGaugeCollector()

if not is_multiprocess_enabled():
    REGISTRY.register(DATABASE_GAUGES)

# Dead-process cleanup targets live-mode gauge files only (every live
# mode name starts with "live"). Counter and histogram files of dead
# processes must stay: removing one drops its share from the merged
# counter, which Prometheus reads as a counter reset.
_DEAD_PID_FILE_RE = re.compile(r"^gauge_live[a-z]*_(\d+)\.db$")

_COLLECT_LOCK_NAME = ".incidentrelay-metrics.lock"


@contextmanager
def _file_lock(path, exclusive):
    try:
        handle = open(path, "a+")
    except OSError:
        yield
        return

    try:
        try:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
            )
        except OSError:
            # Locks are best effort: work without one if the
            # filesystem refuses them.
            pass

        yield
    finally:
        try:
            handle.close()
        except OSError:
            pass


def _pid_alive(pid):
    """True when a process with this PID exists on the local host."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Unknown failure: assume the file still belongs to something.
        return True

    return True


def _cleanup_dead_process_files(path):
    """
    Remove live-mode gauge files of dead processes, like
    prometheus_client.multiprocess.mark_process_dead(). Counter and
    histogram files are kept so the merged counters never drop.
    """

    try:
        filenames = os.listdir(path)
    except OSError:
        return

    dead_pids = set()

    for filename in filenames:
        match = _DEAD_PID_FILE_RE.match(filename)

        if match is None:
            continue

        pid = int(match.group(1))

        if pid == os.getpid() or _pid_alive(pid):
            continue

        dead_pids.add(pid)

    for pid in dead_pids:
        mark_process_dead(pid, path)


def _init_multiprocess_directory():
    if _MULTIPROC_DIR is None or not Config.METRICS_ENABLED:
        return

    try:
        os.makedirs(_MULTIPROC_DIR, exist_ok=True)
    except OSError:
        logger.exception(
            "PROMETHEUS_MULTIPROC_DIR %s is not usable",
            _MULTIPROC_DIR,
        )
        raise

    with _file_lock(
        os.path.join(_MULTIPROC_DIR, _COLLECT_LOCK_NAME),
        exclusive=True,
    ):
        _cleanup_dead_process_files(_MULTIPROC_DIR)


_init_multiprocess_directory()


def record_worker_heartbeat(
    worker,
    *,
    min_interval_seconds=WORKER_HEARTBEAT_MIN_INTERVAL_SECONDS,
):
    """Persist one rate-limited worker heartbeat in app_lock."""

    lock_name = WORKER_HEARTBEAT_LOCK_NAMES.get(worker)
    if lock_name is None:
        raise ValueError(f"unsupported worker heartbeat: {worker}")

    monotonic_now = time.monotonic()
    previous_attempt = _WORKER_HEARTBEAT_LAST_ATTEMPT.get(worker)
    if (
        previous_attempt is not None
        and monotonic_now - previous_attempt
        < max(float(min_interval_seconds), 0.0)
    ):
        return True

    # Rate-limit failures too so a tight worker loop cannot hammer an
    # already unhealthy database.
    _WORKER_HEARTBEAT_LAST_ATTEMPT[worker] = monotonic_now

    db = None
    db_was_closed = True
    try:
        db = init_database()
        db_was_closed = db.is_closed()
        if db_was_closed:
            db.connect(reuse_if_open=True)

        touch_lock(
            lock_name,
            owner=f"{worker}:{os.getpid()}@{socket.gethostname()}",
            ttl_seconds=int(
                getattr(Config, "SCHEDULER_LOCK_TTL_SECONDS", 120)
            ),
        )
        return True
    except Exception:
        logger.exception("%s worker heartbeat update failed", worker)
        return False
    finally:
        if db is not None and db_was_closed and not db.is_closed():
            try:
                db.close()
            except Exception:
                pass


def render_exposition():
    if not is_multiprocess_enabled():
        return generate_latest(REGISTRY)

    path = multiprocess_dir()

    with _file_lock(
        os.path.join(path, _COLLECT_LOCK_NAME),
        exclusive=False,
    ):
        registry = CollectorRegistry()
        MultiProcessCollector(registry, path=path)
        registry.register(DATABASE_GAUGES)

        return generate_latest(registry)


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
