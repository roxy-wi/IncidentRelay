import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import SchedulerAlreadyRunningError, SchedulerNotRunningError

from app.db import database_proxy as db
from app.settings import Config
from app.services.alerts.notification_queue import process_due_alert_group_notifications
from app.services.alerts.lifecycle import logger as send_unacked_reminders
from app.services.db_lock import acquire_db_lock, release_db_lock
from app.services.notifications.shift_notifications import (
    send_due_oncall_shift_email_notifications,
    send_due_oncall_shift_mattermost_notifications,
)
from app.services.notifications.rules import process_due_user_notifications
from app.services.incidents.responders import expire_due_incident_responders
from app.services.alerts.explain_cleanup import cleanup_alert_explain_traces
from app.services.service_catalog.impact_snapshots import capture_scheduled_service_impact_snapshot
from app.services.heartbeats.service import process_overdue_heartbeats
from app.modules.common import utc_now

logger = logging.getLogger("oncall.scheduler")
_scheduler = None


def reminder_job():
    """
    Run reminder job under a database lock.

    The scheduler runs outside Flask request hooks, so it opens and closes
    a database connection explicitly for the APScheduler worker thread.
    """
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("reminder_job")
        if not owner:
            logger.debug("reminder job skipped because lock is busy")
            return 0

        logger.info("reminder job started")

        count = send_unacked_reminders()

        logger.info(
            "reminder job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "reminders_processed": count,
                }
            },
        )

        return count

    except Exception:
        logger.exception("reminder job failed")
        return 0

    finally:
        if owner:
            release_db_lock("reminder_job", owner)

        if not db.is_closed():
            db.close()


def oncall_shift_email_job():
    """
    Send on-call shift start/end email notifications under a database lock.
    """
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("oncall_shift_email_job")

        if not owner:
            logger.debug("on-call shift email job skipped because lock is busy")
            return 0

        logger.info("on-call shift email job started")

        count = send_due_oncall_shift_email_notifications()

        logger.info(
            "on-call shift email job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "oncall_shift_emails_sent": count,
                }
            },
        )

        return count

    except Exception:
        logger.exception("on-call shift email job failed")
        return 0

    finally:
        if owner:
            release_db_lock("oncall_shift_email_job", owner)

        if not db.is_closed():
            db.close()


def oncall_shift_mattermost_job():
    """
    Send personal Mattermost on-call shift start notifications under a database lock.
    """
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("oncall_shift_mattermost_job")

        if not owner:
            logger.debug("on-call shift Mattermost job skipped because lock is busy")
            return 0

        logger.info("on-call shift Mattermost job started")

        count = send_due_oncall_shift_mattermost_notifications()

        logger.info(
            "on-call shift Mattermost job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "oncall_shift_mattermost_sent": count,
                }
            },
        )

        return count

    except Exception:
        logger.exception("on-call shift Mattermost job failed")
        return 0

    finally:
        if owner:
            release_db_lock("oncall_shift_mattermost_job", owner)

        if not db.is_closed():
            db.close()


def user_notification_rules_job():
    """Send due delayed user notification rules under a database lock."""
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("user_notification_rules_job")

        if not owner:
            logger.debug("user notification rules job skipped because lock is busy")
            return 0

        logger.info("user notification rules job started")

        count = process_due_user_notifications()

        logger.info(
            "user notification rules job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "user_notification_deliveries_processed": count,
                }
            },
        )

        return count

    except Exception:
        logger.exception("user notification rules job failed")
        return 0

    finally:
        if owner:
            release_db_lock("user_notification_rules_job", owner)

        if not db.is_closed():
            db.close()


def alert_group_notification_job():
    """Send due alert group notifications under a database lock."""

    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("alert_group_notification_job")

        if not owner:
            logger.debug("alert group notification job skipped because lock is busy")
            return {"processed": 0, "sent": 0, "skipped": 0, "failed": 0}

        logger.info("alert group notification job started")

        result = process_due_alert_group_notifications(
            limit=int(getattr(Config, "ALERT_GROUP_NOTIFICATION_BATCH_SIZE", 100))
        )

        logger.info(
            "alert group notification job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "processed": result.get("processed", 0),
                    "sent": result.get("sent", 0),
                    "skipped": result.get("skipped", 0),
                    "failed": result.get("failed", 0),
                }
            },
        )

        return result

    except Exception:
        logger.exception("alert group notification job failed")
        return {"processed": 0, "sent": 0, "skipped": 0, "failed": 1}

    finally:
        if owner:
            release_db_lock("alert_group_notification_job", owner)

        if not db.is_closed():
            db.close()


def incident_responder_expire_job():
    """Expire pending incident responder requests under a database lock."""
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("incident_responder_expire_job")
        if not owner:
            logger.debug(
                "incident responder expire job skipped because lock is busy"
            )
            return {
                "processed": 0,
                "expired": 0,
                "skipped": 0,
            }

        logger.info("incident responder expire job started")

        result = expire_due_incident_responders(
            limit=int(
                getattr(
                    Config,
                    "INCIDENT_RESPONDER_EXPIRE_BATCH_SIZE",
                    100,
                )
            )
        )

        logger.info(
            "incident responder expire job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "processed": result.get("processed", 0),
                    "expired": result.get("expired", 0),
                    "skipped": result.get("skipped", 0),
                }
            },
        )

        return result

    except Exception:
        logger.exception("incident responder expire job failed")
        return {
            "processed": 0,
            "expired": 0,
            "skipped": 0,
        }

    finally:
        if owner:
            release_db_lock("incident_responder_expire_job", owner)

        if not db.is_closed():
            db.close()


def alert_explain_trace_cleanup_job():
    """Delete old alert explain traces under a database lock."""
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("alert_explain_trace_cleanup_job")

        if not owner:
            logger.debug("alert explain trace cleanup job skipped because lock is busy")
            return {
                "traces_deleted": 0,
                "steps_deleted": 0,
            }

        retention_days = int(
            getattr(Config, "ALERT_EXPLAIN_TRACE_RETENTION_DAYS", 30)
        )

        logger.info(
            "alert explain trace cleanup job started",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "retention_days": retention_days,
                }
            },
        )

        result = cleanup_alert_explain_traces(
            retention_days=retention_days,
        )

        logger.info(
            "alert explain trace cleanup job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "traces_deleted": result.get("traces_deleted", 0),
                    "steps_deleted": result.get("steps_deleted", 0),
                    "cutoff": str(result.get("cutoff")),
                }
            },
        )

        return result

    except Exception:
        logger.exception("alert explain trace cleanup job failed")

        return {
            "traces_deleted": 0,
            "steps_deleted": 0,
            "failed": 1,
        }

    finally:
        if owner:
            release_db_lock("alert_explain_trace_cleanup_job", owner)

        if not db.is_closed():
            db.close()


def heartbeat_overdue_job():
    """Open incidents for overdue heartbeat/dead-man checks under a database lock."""
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("heartbeat_overdue_job")

        if not owner:
            logger.debug("heartbeat overdue job skipped because lock is busy")
            return {"processed": 0, "overdue": 0, "unchanged": 0, "failed": 0}

        logger.info("heartbeat overdue job started")

        result = process_overdue_heartbeats(
            limit=int(getattr(Config, "HEARTBEAT_CHECK_BATCH_SIZE", 100))
        )

        logger.info(
            "heartbeat overdue job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "processed": result.get("processed", 0),
                    "overdue": result.get("overdue", 0),
                    "unchanged": result.get("unchanged", 0),
                    "failed": result.get("failed", 0),
                }
            },
        )

        return result

    except Exception:
        logger.exception("heartbeat overdue job failed")
        return {"processed": 0, "overdue": 0, "unchanged": 0, "failed": 1}

    finally:
        if owner:
            release_db_lock("heartbeat_overdue_job", owner)

        if not db.is_closed():
            db.close()


def service_impact_snapshot_job():
    """Capture Service Impact snapshots under a database lock."""
    if db.is_closed():
        db.connect(reuse_if_open=True)

    owner = None

    try:
        owner = acquire_db_lock("service_impact_snapshot_job")

        if not owner:
            logger.debug("service impact snapshot job skipped because lock is busy")
            return {
                "items": 0,
                "deleted_old_snapshots": 0,
            }

        logger.info("service impact snapshot job started")

        result = capture_scheduled_service_impact_snapshot(
            retention_days=int(getattr(Config, "SERVICE_IMPACT_SNAPSHOT_RETENTION_DAYS", 365))
        )

        logger.info(
            "service impact snapshot job finished",
            extra={
                "extra": {
                    "event_type": "scheduler",
                    "snapshot_items": result.get("items", 0),
                    "deleted_old_snapshots": result.get("deleted_old_snapshots", 0),
                }
            },
        )

        return result

    except Exception:
        logger.exception("service impact snapshot job failed")
        return {
            "items": 0,
            "deleted_old_snapshots": 0,
            "failed": 1,
        }

    finally:
        if owner:
            release_db_lock("service_impact_snapshot_job", owner)

        if not db.is_closed():
            db.close()


def start_scheduler():
    """
    Start the background scheduler.

    The scheduler is kept as a module-level singleton so scheduler_worker can
    stop it cleanly during SIGTERM/SIGINT shutdown.
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("scheduler already running")
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        reminder_job,
        "interval",
        seconds=Config.REMINDER_INTERVAL_SECONDS,
        max_instances=1,
        coalesce=True,
        next_run_time=utc_now(),
        id="reminder_job",
        replace_existing=True,
    )

    _scheduler.add_job(
        oncall_shift_email_job,
        "interval",
        seconds=int(
            getattr(
                Config,
                "ONCALL_SHIFT_EMAIL_CHECK_INTERVAL_SECONDS",
                Config.REMINDER_INTERVAL_SECONDS,
            )
        ),
        max_instances=1,
        coalesce=True,
        next_run_time=utc_now(),
        id="oncall_shift_email_job",
        replace_existing=True,
    )

    if bool(getattr(Config, "ONCALL_SHIFT_MATTERMOST_ENABLED", True)):
        _scheduler.add_job(
            oncall_shift_mattermost_job,
            "interval",
            seconds=int(
                getattr(
                    Config,
                    "ONCALL_SHIFT_MATTERMOST_CHECK_INTERVAL_SECONDS",
                    Config.REMINDER_INTERVAL_SECONDS,
                )
            ),
            max_instances=1,
            coalesce=True,
            next_run_time=utc_now(),
            id="oncall_shift_mattermost_job",
            replace_existing=True,
        )

    _scheduler.add_job(
        user_notification_rules_job,
        "interval",
        seconds=int(
            getattr(
                Config,
                "USER_NOTIFICATION_RULES_CHECK_INTERVAL_SECONDS",
                30,
            )
        ),
        max_instances=1,
        coalesce=True,
        next_run_time=utc_now(),
        id="user_notification_rules_job",
        replace_existing=True,
    )

    _scheduler.add_job(
        alert_group_notification_job,
        "interval",
        seconds=int(getattr(Config, "ALERT_GROUP_NOTIFICATION_CHECK_INTERVAL_SECONDS", 10)),
        max_instances=1,
        coalesce=True,
        next_run_time=utc_now(),
        id="alert_group_notification_job",
        replace_existing=True,
    )

    _scheduler.add_job(
        incident_responder_expire_job,
        "interval",
        seconds=int(
            getattr(
                Config,
                "INCIDENT_RESPONDER_EXPIRE_CHECK_INTERVAL_SECONDS",
                30,
            )
        ),
        max_instances=1,
        coalesce=True,
        next_run_time=utc_now(),
        id="incident_responder_expire_job",
        replace_existing=True,
    )

    _scheduler.add_job(
        alert_explain_trace_cleanup_job,
        "interval",
        seconds=int(
            getattr(
                Config,
                "ALERT_EXPLAIN_TRACE_CLEANUP_INTERVAL_SECONDS",
                86400,
            )
        ),
        max_instances=1,
        coalesce=True,
        next_run_time=utc_now(),
        id="alert_explain_trace_cleanup_job",
        replace_existing=True,
    )

    if bool(getattr(Config, "HEARTBEATS_ENABLED", True)):
        _scheduler.add_job(
            heartbeat_overdue_job,
            "interval",
            seconds=int(getattr(Config, "HEARTBEAT_CHECK_INTERVAL_SECONDS", 30)),
            max_instances=1,
            coalesce=True,
            next_run_time=utc_now(),
            id="heartbeat_overdue_job",
            replace_existing=True,
        )

    if bool(getattr(Config, "SERVICE_IMPACT_SNAPSHOT_ENABLED", True)):
        _scheduler.add_job(
            service_impact_snapshot_job,
            "interval",
            seconds=int(getattr(Config, "SERVICE_IMPACT_SNAPSHOT_INTERVAL_SECONDS", 300)),
            max_instances=1,
            coalesce=True,
            next_run_time=utc_now(),
            id="service_impact_snapshot_job",
            replace_existing=True,
        )

    try:
        _scheduler.start()
    except SchedulerAlreadyRunningError:
        logger.warning("scheduler was already started")

    logger.info(
        "scheduler started",
        extra={
            "extra": {
                "event_type": "scheduler",
                "reminder_interval_seconds": Config.REMINDER_INTERVAL_SECONDS,
                "lock_ttl_seconds": Config.SCHEDULER_LOCK_TTL_SECONDS,
            }
        },
    )

    return _scheduler


def stop_scheduler(wait=False):
    """
    Stop the background scheduler if it is running.
    """
    global _scheduler

    if not _scheduler:
        return

    try:
        if _scheduler.running:
            _scheduler.shutdown(wait=wait)
            logger.info("scheduler stopped")
    except SchedulerNotRunningError:
        pass
    finally:
        _scheduler = None
