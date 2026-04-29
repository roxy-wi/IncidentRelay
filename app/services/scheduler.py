from apscheduler.schedulers.background import BackgroundScheduler

from app.settings import Config
from app.services.alerts import send_unacked_reminders
from app.services.db_lock import acquire_db_lock, release_db_lock


def reminder_job():
    """
    Run reminder job under a database lock.
    """

    owner = acquire_db_lock("reminder_job")
    if not owner:
        return 0
    try:
        return send_unacked_reminders()
    finally:
        release_db_lock("reminder_job", owner)


def start_scheduler():
    """
    Start background scheduler.
    """

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        reminder_job,
        "interval",
        seconds=Config.REMINDER_INTERVAL_SECONDS,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
