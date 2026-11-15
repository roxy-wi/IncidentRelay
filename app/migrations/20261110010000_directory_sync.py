"""Add configurable directory and on-call synchronization."""

from app.db import init_database
from app.modules.db.models import (
    DirectorySyncBinding, DirectorySyncCurrent, DirectorySyncShift, DirectorySyncSource,
)

MODELS = [DirectorySyncSource, DirectorySyncBinding, DirectorySyncShift, DirectorySyncCurrent]


def upgrade():
    """Create synchronization state without changing existing rotations."""
    init_database().create_tables(MODELS, safe=True)


def downgrade():
    """Remove synchronization state."""
    init_database().drop_tables(list(reversed(MODELS)), safe=True)
