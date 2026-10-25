"""Normalize historic audit action names to the single dotted convention.

This migration intentionally removes old action names, as requested for the
breaking audit contract. AlertEvent lifecycle names are independent and retained.
"""
from app.db import init_database
from app.modules.db.models import AuditLog


def upgrade():
    init_database()
    replacements = {
        "incident_declared": "incident.declare",
        "incident_updated": "incident.update",
        "incident_assignee_changed": "incident.assignee_change",
        "incident_status_changed": "incident.status_change",
        "incident_group_linked": "incident.group_link",
        "incident_group_unlinked": "incident.group_unlink",
        "incident_reopened_by_alert_group": "incident.reopen_by_alert_group",
        "alert_group_reopened": "alert_group.reopen",
        "alert_group_assignee_changed": "alert_group.assignee_change",
    }
    for before, after in replacements.items():
        AuditLog.update(action=after).where(AuditLog.action == before).execute()


def downgrade():
    """Do not recreate deprecated audit names during downgrade."""
    pass
