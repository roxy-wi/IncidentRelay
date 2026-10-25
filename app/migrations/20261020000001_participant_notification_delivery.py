"""Add persistent, retryable incident-participant notification deliveries."""

from app.db import init_database
from app.modules.db.models import ParticipantNotificationDelivery


db = init_database()


def upgrade():
    """Create the participant notification delivery queue table."""
    db.create_tables([ParticipantNotificationDelivery], safe=True)


def downgrade():
    """Remove the participant notification delivery queue table."""
    db.drop_tables([ParticipantNotificationDelivery], safe=True)
