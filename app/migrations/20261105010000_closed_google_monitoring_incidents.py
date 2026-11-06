"""Remember terminal Google Cloud Monitoring incident IDs across deliveries."""

from app.modules.db.models import ClosedGoogleMonitoringIncident


def upgrade():
    """Create an empty table; existing alert sources need no backfill."""
    ClosedGoogleMonitoringIncident.create_table(safe=True)


def downgrade():
    """Remove terminal Google incident identities."""
    ClosedGoogleMonitoringIncident.drop_table(safe=True)
