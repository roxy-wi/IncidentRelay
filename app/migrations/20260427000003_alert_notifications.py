from app.db import init_database
from app.modules.db.models import AlertNotification


db = init_database()


def upgrade():
    """
    Create delivery tracking for external notification messages.
    """

    db.create_tables([AlertNotification], safe=True)


def downgrade():
    """
    Drop delivery tracking for external notification messages.
    """

    db.drop_tables([AlertNotification], safe=True)
