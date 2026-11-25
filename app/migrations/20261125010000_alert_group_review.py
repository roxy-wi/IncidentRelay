"""Add optional AlertGroup assessments without rewriting existing alert groups."""

from app.db import init_database
from app.modules.db.models import AlertGroupReview


def upgrade():
    init_database().create_tables([AlertGroupReview], safe=True)


def downgrade():
    db = init_database()
    if db.table_exists(AlertGroupReview._meta.table_name) and AlertGroupReview.select().exists():
        raise RuntimeError("Cannot drop stored AlertGroup reviews")
    db.drop_tables([AlertGroupReview], safe=True)
