"""Add operator-controlled alert-group shelving."""

from app.db import init_database
from app.modules.db.models import AlertGroupShelve


db = init_database()


def upgrade():
    """Create alert-group shelving history storage."""
    db.create_tables([AlertGroupShelve], safe=True)


def downgrade():
    """Remove alert-group shelving history storage."""
    db.drop_tables([AlertGroupShelve], safe=True)
