from app.db import init_database
from app.modules.db.models import (
    ApiToken,
    Alert,
    AlertEvent,
    AlertNotification,
    AlertRoute,
    AlertRouteChannel,
    Group,
    AppLock,
    AuditLog,
    Migration,
    MigrationState,
    NotificationChannel,
    Role,
    Rotation,
    RotationMember,
    RotationOverride,
    Silence,
    Team,
    UserGroup,
    TeamUser,
    User,
    UserRole,
    Version,
)
from app.version import get_service_version


db = init_database()


MODELS = [
    Migration,
    MigrationState,
    Version,
    Group,
    User,
    UserGroup,
    Role,
    UserRole,
    Team,
    TeamUser,
    Rotation,
    RotationMember,
    RotationOverride,
    NotificationChannel,
    AlertRoute,
    AlertRouteChannel,
    Alert,
    AlertEvent,
    AlertNotification,
    Silence,
    ApiToken,
    AuditLog,
    AppLock,
]


def upgrade():
    """
    Create the initial database schema.
    """

    db.create_tables(MODELS, safe=True)
    Version.get_or_create(version=get_service_version())


def downgrade():
    """
    Drop all application tables.
    """

    db.drop_tables(list(reversed(MODELS)), safe=True)
