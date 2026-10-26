"""Create Incident-owned collaboration tables for version 2.5."""

from app.db import init_database
from app.modules.db.models import IncidentComment, IncidentService


def upgrade():
    """Create new tables without modifying existing AlertGroup records."""
    db = init_database()
    db.create_tables([IncidentComment, IncidentService], safe=True)


def downgrade():
    """Drop only the collaboration tables introduced by this migration."""
    db = init_database()
    db.drop_tables([IncidentService, IncidentComment], safe=True)
