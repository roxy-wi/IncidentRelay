"""Add shared login-throttling state."""

from app.db import init_database
from app.modules.db.models import LoginThrottle


db = init_database()


def upgrade() -> None:
    if not db.table_exists(LoginThrottle._meta.table_name):
        db.create_tables([LoginThrottle], safe=True)


def downgrade() -> None:
    if db.table_exists(LoginThrottle._meta.table_name):
        db.drop_tables([LoginThrottle], safe=True)
