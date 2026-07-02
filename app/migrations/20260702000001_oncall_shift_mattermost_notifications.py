"""Add dedup table for personal Mattermost on-call shift notifications."""

from app.db import init_database
from app.modules.db.models import OnCallShiftMattermostNotification


db = init_database()


def upgrade():
    """Create Mattermost shift notification dedup table."""
    db.create_tables(
        [OnCallShiftMattermostNotification],
        safe=True,
    )


def downgrade():
    """Drop Mattermost shift notification dedup table."""
    db.drop_tables(
        [OnCallShiftMattermostNotification],
        safe=True,
    )
