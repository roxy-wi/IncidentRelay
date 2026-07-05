"""Add persisted alert group dependency correlations."""

from app.db import init_database
from app.modules.db.models import AlertGroupCorrelation


db = init_database()


def upgrade():
    db.create_tables([AlertGroupCorrelation], safe=True)


def rollback():
    db.drop_tables([AlertGroupCorrelation], safe=True)


def downgrade():
    rollback()
