"""Database queue gauges, shared across scheduler and web processes."""

import logging

from peewee import fn
from prometheus_client.metrics_core import GaugeMetricFamily

from app.db import init_database
from app.modules.common import utc_now
from app.modules.db.models import ChangeJob, ChangeServiceReference


def change_worker_gauges():
    """Expose bounded categories without Change, Team or Service identifiers."""
    database = None
    opened = False
    try:
        database = init_database()
        opened = database.is_closed()
        if opened:
            database.connect(reuse_if_open=True)
        jobs = list(
            ChangeJob.select(
                ChangeJob.job_type,
                ChangeJob.state,
                fn.COUNT(ChangeJob.id),
                fn.MIN(ChangeJob.next_attempt_at),
            )
            .group_by(ChangeJob.job_type, ChangeJob.state)
            .tuples()
        )
        refs = list(
            ChangeServiceReference.select(
                ChangeServiceReference.resolution_status,
                fn.COUNT(ChangeServiceReference.id),
            )
            .group_by(ChangeServiceReference.resolution_status)
            .tuples()
        )
        failures = list(
            ChangeJob.select(ChangeJob.last_error_class, fn.COUNT(ChangeJob.id))
            .where(ChangeJob.state == "dead")
            .group_by(ChangeJob.last_error_class)
            .tuples()
        )
    except Exception as error:
        logging.getLogger("incidentrelay.metrics").error(
            "Change queue metrics unavailable: %s", type(error).__name__
        )
        return
    finally:
        if database is not None and opened and not database.is_closed():
            database.close()
    queue = GaugeMetricFamily(
        "incidentrelay_change_jobs",
        "Durable Change jobs by type/state.",
        labels=("job_type", "state"),
    )
    age = GaugeMetricFamily(
        "incidentrelay_change_queue_oldest_due_age_seconds",
        "Age since the oldest queued job became due.",
        labels=("job_type", "state"),
    )
    for job_type, state, count, due in jobs:
        queue.add_metric((job_type, state), count)
        if state in {"pending", "running"}:
            age.add_metric((job_type, state), max(0, (utc_now() - due).total_seconds()))
    reference_counts = GaugeMetricFamily(
        "incidentrelay_change_references",
        "Submitted Change references by resolution state.",
        labels=("state",),
    )
    for state, count in refs:
        reference_counts.add_metric((state,), count)
    errors = GaugeMetricFamily(
        "incidentrelay_change_dead_jobs",
        "Dead jobs by bounded error category.",
        labels=("error_class",),
    )
    totals = {}
    for error, count in failures:
        category = (
            error
            if error in {"internal_error", "transient_database", "attempts_exhausted"}
            else "other"
        )
        totals[category] = totals.get(category, 0) + count
    for category, count in totals.items():
        errors.add_metric((category,), count)
    yield queue
    yield age
    yield reference_counts
    yield errors
