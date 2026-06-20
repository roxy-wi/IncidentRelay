from app.db import init_database
from app.modules.db.models import AlertExplainStep, AlertExplainTrace

db = init_database()


def upgrade():
    """Create alert explain trace tables."""
    db.create_tables(
        [
            AlertExplainTrace,
            AlertExplainStep,
        ],
        safe=True,
    )


def downgrade():
    """Drop alert explain trace tables."""
    db.drop_tables(
        [
            AlertExplainStep,
            AlertExplainTrace,
        ],
        safe=True,
    )
