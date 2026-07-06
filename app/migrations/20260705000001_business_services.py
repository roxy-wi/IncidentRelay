"""Add business services and business impact tables."""

from app.db import init_database
from app.modules.db.models import (
    BusinessService,
    BusinessServiceComponent,
    BusinessServiceIncidentImpact,
    BusinessServiceStatusHistory,
)


db = init_database()


def upgrade():
    db.create_tables([
        BusinessService,
        BusinessServiceComponent,
        BusinessServiceStatusHistory,
        BusinessServiceIncidentImpact,
    ], safe=True)


def rollback():
    db.drop_tables([
        BusinessServiceIncidentImpact,
        BusinessServiceStatusHistory,
        BusinessServiceComponent,
        BusinessService,
    ], safe=True)


def downgrade():
    rollback()
