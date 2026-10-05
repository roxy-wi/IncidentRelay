"""
Prometheus metric collectors for IncidentRelay.

Owns the collectors the /metrics endpoint serves (app/views/metrics_view.py)
and render_exposition(), the function that turns them into the text
exposition. The module is a leaf on purpose: the view imports it for the
exposition, and services (alert intake, the alert-group repo layer, the
scheduler) import it to record business events — so nothing here may
import views or other services.

IncidentRelay runs several processes against one scrape target: the
Gunicorn web workers (four in the shipped systemd unit) plus the
scheduler and the Telegram/Slack workers as separate daemons. Two
mechanisms keep the exposition correct for that model:

- Counters and histograms are recorded by every process into one
  shared directory when PROMETHEUS_MULTIPROC_DIR is set (the
  prometheus_client multiprocess mode). render_exposition() merges all
  process files at scrape time, so a scrape always covers every event
  every process handled. Deployment units set the variable to one
  shared per-host directory (systemd: /run/incidentrelay/metrics,
  Docker: /var/lib/incidentrelay/metrics on the shared data volume).
  Without the variable everything falls back to one in-process
  registry, which is correct for single-process development runs.
  Files of processes that exited keep contributing their last values
  until the next IncidentRelay process starts and removes them, so
  counters only ever reset on a restart of a contributing process —
  which Prometheus rate() handles natively.

- The database-derived gauges (database and migration state, notification
  deliveries, failing notification targets, scheduler heartbeat, build
  info) are never stored per process. DatabaseGaugeCollector computes
  them at scrape time from the shared database, exactly once per scrape,
  and they never appear more than once in the exposition regardless of
  the process count. Like the readiness probe (app/services/readiness.py)
  it manages its own connection and never raises: on a database outage
  the delivery gauges are absent, database_up reads 0 and the heartbeat
  reads 0, with a warning in the logs.

Files of processes that died (a Gunicorn worker killed on timeout, a
crashed daemon) would keep being merged forever, so render_exposition()
removes files whose recorded PID is no longer alive before collecting.
A removed file takes its process's counter share with it: Prometheus
treats that as a counter reset, which rate() handles natively, and it
is strictly better than counting a process that no longer exists.
"""

import fcntl
import logging
import os
import re
from contextlib import contextmanager
from datetime import timezone

from peewee import fn
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.multiprocess import MultiProcessCollector
from prometheus_client.registry import Collector

from app.db import init_database
from app.modules.db.models import (
    AlertNotification,
    AppLock,
    UserNotificationDelivery,
)
from app.services.readiness import run_readiness_probe
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

# Lock name of the never-released row the scheduler refreshes as its
# heartbeat; app/services/scheduler.py writes it, the gauge reads it.
SCHEDULER_HEARTBEAT_LOCK_NAME = "scheduler_heartbeat"


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
    """
    Compute the database-derived gauges at scrape time.

    None of these values may live in a process registry: in multiprocess
    mode every process would report its own copy and the exposition would
    repeat or mis-aggregate them. Computing them here, once per scrape,
    keeps one authoritative value and keeps working while the database
    is down — which is when the gauges matter most.
    """

    def collect(self):
        yield from self._database_gauges()
        yield from self._notification_gauges()
        yield self._build_info_gauge()

    def _database_gauges(self):
        """
        Report database_up and migrations_pending from the readiness probe.

        Every failure path only degrades the gauges and logs a warning;
        the exposition itself never fails.
        """

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
            migrations_pending.add_metric([], 0)
            logger.warning(
                "metrics database check failed",
                exc_info=probe.database_error,
            )
            yield database_up
            yield migrations_pending
            return

        database_up.add_metric([], 1)

        if probe.migration_error is not None:
            # The database answers but the migration state is unknown.
            # Report no pending migrations: /readyz is the authoritative
            # readiness signal.
            migrations_pending.add_metric([], 0)
            logger.warning(
                "metrics migration check failed",
                exc_info=probe.migration_error,
            )
            yield database_up
            yield migrations_pending
            return

        migrations_pending.add_metric([], len(probe.pending))
        yield database_up
        yield migrations_pending

    def _notification_gauges(self):
        """
        Report deliveries, failing targets and the scheduler heartbeat.

        Opens its own connection and never raises: on failure the
        delivery gauges are absent, the heartbeat reads 0 and the reason
        is logged, so a scrape during a database outage still succeeds.
        """

        deliveries = GaugeMetricFamily(
            "incidentrelay_user_notification_deliveries",
            "Recorded per-user notification deliveries by method and outcome.",
            labels=("method", "status"),
        )
        failing = GaugeMetricFamily(
            "incidentrelay_notification_targets_failing",
            "Notification channels whose last delivery ended in an error.",
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
                deliveries.add_metric(
                    (method, status),
                    total,
                )

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
                failing.add_metric((provider,), total)

            heartbeat.add_metric(
                [],
                self._scheduler_heartbeat_value(),
            )
        except Exception as exc:
            heartbeat.add_metric([], 0)
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

        yield deliveries
        yield failing
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

# Single-process mode renders straight from REGISTRY, so the database
# gauges join the counters there. In multiprocess mode render_exposition()
# registers the collector on a fresh per-scrape registry instead; either
# way the gauges are computed exactly once per scrape.
if not is_multiprocess_enabled():
    REGISTRY.register(DATABASE_GAUGES)

# Matches the per-process files prometheus_client writes:
# counter_<pid>.db, histogram_<pid>.db, gauge_<mode>_<pid>.db. Anything
# else in the directory (lock files, foreign files) must not be touched.
_MULTIPROC_FILE_RE = re.compile(r"^[a-z]+(?:_[a-z]+)?_(\d+)\.db$")

# Serializes dead-file cleanup against the collection step across
# processes: cleanup removes files, and MultiProcessCollector would raise
# if a file vanished between its glob and its read. Best effort — if the
# filesystem refuses locks, scraping still works, races are just possible.
_COLLECT_LOCK_NAME = ".incidentrelay-metrics.lock"


@contextmanager
def _file_lock(path, exclusive):
    try:
        handle = open(path, "a+")
    except OSError:
        yield
        return

    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
        )
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
    """Remove multiprocess files whose PID is no longer alive.

    Runs at process startup (see _init_multiprocess_directory), not at
    scrape time: until then, files of exited processes keep contributing
    their last values, which keeps counters monotonic across worker
    churn while bounding the directory growth across restarts.
    """

    try:
        filenames = os.listdir(path)
    except OSError:
        return

    for filename in filenames:
        match = _MULTIPROC_FILE_RE.match(filename)

        if match is None:
            continue

        pid = int(match.group(1))

        if pid == os.getpid() or _pid_alive(pid):
            continue

        try:
            os.remove(os.path.join(path, filename))
        except OSError:
            # Another starting process removed it first.
            pass


def _init_multiprocess_directory():
    """
    Create the multiprocess directory and drop files of dead processes.

    Runs once at import, from every process that contributes to or
    serves the exposition. prometheus_client opens its per-process
    files lazily but requires the directory to exist; creating it here
    fails the process at startup with a clear error instead of turning
    every later scrape or recorded event into a 500 — a configured
    directory that cannot be created is a broken deployment, and
    silently continuing would mean serving the wrong (process-local)
    metrics. The cleanup holds the lock exclusively so it cannot race
    a scrape that is currently reading the files it removes.
    """

    if _MULTIPROC_DIR is None:
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
    """
    Return the Prometheus text exposition for the current process model.

    Multiprocess mode merges the files of every contributing process —
    web workers and the scheduler/Telegram/Slack daemons alike — and
    adds the database gauges. Single-process mode renders REGISTRY,
    which already carries the counters and the database gauges. The
    shared lock keeps a concurrent process startup from removing a file
    between the collector's glob and its read.
    """

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
