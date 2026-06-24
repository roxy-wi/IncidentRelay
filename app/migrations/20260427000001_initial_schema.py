from peewee import ForeignKeyField

from app.db import init_database
from app.modules.db.models import (
    ApiToken,
    Alert,
    AlertEvent,
    AlertNotification,
    AlertNotificationEvent,
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
    SsoProvider,
    SsoIdentity,
    SsoGroupMapping,
)

db = init_database()

MODELS = [
    Migration,
    MigrationState,
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
    AlertNotificationEvent,
    Silence,
    ApiToken,
    SsoProvider,
    SsoIdentity,
    SsoGroupMapping,
    AuditLog,
    AppLock,
]

def _expand_model_dependencies(models):
    """Include every model referenced by a foreign key."""
    ordered = []
    visited = set()
    visiting = set()

    def visit(model):
        if model in visited:
            return

        if model in visiting:
            return

        visiting.add(model)

        for field in model._meta.sorted_fields:
            if not isinstance(field, ForeignKeyField):
                continue

            related_model = field.rel_model

            if related_model is model:
                continue

            visit(related_model)

        visiting.remove(model)
        visited.add(model)
        ordered.append(model)

    for model in models:
        visit(model)

    return ordered


BOOTSTRAP_MODELS = _expand_model_dependencies(MODELS)


def upgrade():
    """Create the initial database schema."""
    db.create_tables(BOOTSTRAP_MODELS, safe=True)


def downgrade():
    """Drop all application tables created by the initial migration."""
    db.drop_tables(list(reversed(BOOTSTRAP_MODELS)), safe=True)
