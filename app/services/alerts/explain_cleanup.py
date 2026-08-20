from datetime import timedelta

from app.modules.db import alerts_repo
from app.modules.common import utc_now


def cleanup_alert_explain_traces(*, retention_days=None, now=None):
    if retention_days is None:
        retention_days = 0

    retention_days = int(retention_days)

    if retention_days < 0:
        raise ValueError("retention_days must be greater than or equal to 0")

    if retention_days == 0:
        return {
            "traces_deleted": 0,
            "steps_deleted": 0,
            "cutoff": None,
        }

    if now is None:
        now = utc_now()

    cutoff = now - timedelta(days=retention_days)

    return alerts_repo.delete_alert_explain_traces_older_than(cutoff)
