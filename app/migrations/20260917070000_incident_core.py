"""Add first-class Incident core tables for IncidentRelay 2.3."""

from app.db import init_database
from app.modules.db.models import Incident, IncidentAlertGroupLink, IncidentEvent


db = init_database()


def upgrade():
    """Create first-class Incident and AlertGroup link storage."""
    db.create_tables([Incident, IncidentEvent, IncidentAlertGroupLink], safe=True)


def downgrade():
    """Remove Incident core tables in dependency-safe order."""
    db.drop_tables([IncidentAlertGroupLink, IncidentEvent, Incident], safe=True)
