"""Create the installation-wide settings singleton."""

from app.db import init_database
from app.modules.db.models import SystemSettings


def upgrade():
    """Start with Change intake disabled and background processing enabled."""
    with init_database().atomic():
        SystemSettings.create_table(safe=True)
        SystemSettings.insert(id=1).on_conflict_ignore().execute()


def downgrade():
    """Remove system settings when rolling back this migration."""
    SystemSettings.drop_table(safe=True)
