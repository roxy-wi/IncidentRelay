from app.db import init_database
from app.modules.db.models import ServiceImpactSnapshot, ServiceImpactSnapshotItem


db = init_database()


def upgrade():
    """Create historical Service Impact snapshot tables."""
    db.create_tables([ServiceImpactSnapshot, ServiceImpactSnapshotItem], safe=True)


def downgrade():
    db.drop_tables([ServiceImpactSnapshotItem, ServiceImpactSnapshot], safe=True)
