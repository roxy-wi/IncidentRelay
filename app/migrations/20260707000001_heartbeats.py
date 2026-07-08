"""Add first-class heartbeat/dead-man-switch checks."""

from app.db import init_database
from app.modules.db.models import Heartbeat, HeartbeatPing


db = init_database()


def upgrade():
    db.create_tables([Heartbeat, HeartbeatPing], safe=True)


def downgrade():
    db.drop_tables([HeartbeatPing, Heartbeat], safe=True)
