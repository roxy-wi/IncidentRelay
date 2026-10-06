import fcntl
import logging
import os
import re
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
from app.modules.db.models import (
    AlertNotification,
    AppLock,
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

# Lock name of the never-released row the scheduler refreshes as its
# heartbeat; app/services/scheduler.py writes it, the gauge reads it.
SCHEDULER_HEARTBEAT_LOCK_NAME = "scheduler_heartbeat"

# Time window of the *_recent database gauges; the migration
# 20261006070000_metrics_recent_indexes backs its updated_at filters.
# Both delivery tables are mutable: a row created days ago can fail
# today, so the window must follow updated_at, not created_at.
RECENT_WINDOW = timedelta(hours=24)


def multiprocess_dir():
    """Return the configured multiprocess directory, or None."""

    return (
        os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        or os.environ.get("prometheus_multiproc_dir")
        or None
    )


def is_multiprocess_enabled():
    """True when counters are backed by the shared multiprocess directory.

    prometheus_client picks its value class from the same environment
    variables at first import, so this is a deployment-level switch, not
    a runtime setting: it cannot be flipped for a running process.
    """

    return multiprocess_dir() is not None


# Frozen at import: prometheus_client has already picked its value class
# from the same environment, so the process model cannot change later.
_MULTIPROC_DIR = multiprocess_dir()


class DatabaseGaugeCollector(Collector):
    def collect(self):
        yield from self._database_gauges()
        yield from self._notification_gauges()
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

    def _notification_gauges(self):
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
        heartbeat = GaugeMetricFamily(
            "incidentrelay_scheduler_last_run_timestamp_seconds",
            "Unix time of the last scheduler heartbeat, 0 when it never ran.",
        )

        db = None
        db_was_closed = True

        try:
            db = init_database()
            db_was_closed = db.is_closed()

            if db_was_closed:
                db.connect(reuse_if_open=True)

            # Both gauges are windowed so a scrape never scans the full
            # delivery history of a long-lived installation. The window
            # follows updated_at: rows transition in place (pending ->
            # sent/failed, new provider errors), so created_at would
            # miss recent failures of old rows.
            recent_since = utc_now() - RECENT_WINDOW

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

            heartbeat_value = self._scheduler_heartbeat_value()
        except Exception as exc:
            delivery_rows = []
            error_rows = []
            heartbeat_value = 0
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

        for method, status, total in delivery_rows:
            deliveries.add_metric(
                (method, status),
                total,
            )

        for provider, total in error_rows:
            errors.add_metric((provider,), total)

        heartbeat.add_metric([], heartbeat_value)

        yield deliveries
        yield errors
        yield heartbeat

    @staticmethod
    def _scheduler_heartbeat_value():
        """Unix time of the last scheduler heartbeat, 0 when absent."""

        lock = AppLock.get_or_none(
            AppLock.name == SCHEDULER_HEARTBEAT_LOCK_NAME,
        )

        if lock is None or lock.updated_at is None:
            return 0

        # Timestamps are stored as naive UTC values (app/modules/common.py).
        return lock.updated_at.replace(tzinfo=timezone.utc).timestamp()

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

# Live-mode gauge files only: these die with their process. Counter and
# histogram files of dead processes must stay: removing one would drop
# its share from the merged counter, which Prometheus reads as a counter
# reset and rate() distorts on. They keep accumulating until the shared
# directory is cleared on a full redeploy. Every live gauge mode name
# (liveall, livesum, livemin, livemax, livemostrecent) starts with
# "live", the non-live modes (all, sum, max, min, mostrecent) do not.
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
    Remove live-mode gauge files of dead processes.

    This mirrors prometheus_client.multiprocess.mark_process_dead():
    counter and histogram files of dead processes are kept, so the
    merged counters never drop and Prometheus never sees a synthetic
    counter reset when a worker exits.
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
