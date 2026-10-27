"""Persist operational Incident notifications independently of AlertGroups."""

from app.db import init_database
from app.modules.db.models import IncidentNotificationDelivery


def upgrade():
    """Create the delivery ledger without replaying historical events."""
    init_database().create_tables([IncidentNotificationDelivery], safe=True)


def downgrade():
    """Remove the operational notification ledger."""
    init_database().drop_tables([IncidentNotificationDelivery], safe=True)
