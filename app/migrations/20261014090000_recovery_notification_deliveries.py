"""Durable per-target retry and de-duplication of delayed recovery delivery.

Existing AlertGroup queue values remain valid; outstanding recovery groups
will snapshot their recipients on the first due scheduler run after migration.
"""

from app.db import init_database
from app.migrations.introspection import table_exists
from app.modules.db.models import RecoveryNotificationDelivery


db = init_database()


def upgrade():
    db.create_tables([RecoveryNotificationDelivery], safe=True)


def downgrade():
    if table_exists(db, RecoveryNotificationDelivery._meta.table_name):
        db.drop_tables([RecoveryNotificationDelivery], safe=True)
