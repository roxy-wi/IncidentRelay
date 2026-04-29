from datetime import datetime

from app.db import init_database
from app.modules.db.models import Version
from app.version import get_service_version


db = init_database()


def upgrade():
    """
    Store the current service version.
    """

    db.create_tables([Version], safe=True)
    Version.update(updated_at=datetime.utcnow()).execute()
    Version.get_or_create(version=get_service_version())


def downgrade():
    """
    Remove the current service version record.
    """

    Version.delete().where(Version.version == get_service_version()).execute()
