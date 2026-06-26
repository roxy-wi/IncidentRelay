import os
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_DB = ROOT_DIR / "tests" / ".tmp" / "incidentrelay-ci.db"
TEST_CONFIG = ROOT_DIR / "tests" / "incidentrelay.test.conf"

# Must be set before importing app.settings/app.db/app models.
os.environ.setdefault("INCEDENTRELAY_CONFIG_FILE", str(TEST_CONFIG))
os.environ.setdefault("PYTHONPATH", str(ROOT_DIR))

(ROOT_DIR / "tests" / ".tmp").mkdir(parents=True, exist_ok=True)
(ROOT_DIR / "logs").mkdir(parents=True, exist_ok=True)


from app import create_app  # noqa: E402
from app.db import init_database  # noqa: E402
from app.login import create_access_token  # noqa: E402
from tests.factories import create_user  # noqa: E402
from app.modules.db.migrations import migrate  # noqa: E402
from app.modules.db.models import (  # noqa: E402
    Alert,
    AlertEvent,
    AlertNotification,
    AlertNotificationEvent,
    AlertRoute,
    AlertRouteChannel,
    AlertGroup,
    AlertGroupMerge,
    AlertComment,
    ApiToken,
    AppLock,
    AuditLog,
    Group,
    NotificationChannel,
    Role,
    Rotation,
    RotationMember,
    RotationOverride,
    Silence,
    Team,
    TeamUser,
    User,
    UserGroup,
    UserRole,
    RotationLayerRestriction,
    RotationLayerMember,
    RotationLayer,
    SsoProvider,
    SsoIdentity,
    SsoGroupMapping,
    EscalationPolicy,
    EscalationPolicyRule,
    Service,
    ServiceChannel,
    ServiceDependency,
    ServiceLink,
    ServiceRunbook,
    ServiceMatchRule,
    ServiceSlo,
    ServiceStatusHistory,
    MaintenanceWindow,
    MaintenanceWindowService,
    OnCallShiftEmailNotification,
    BrowserPushActionToken,
    BrowserPushSubscription,
    UserNotificationDelivery,
    UserNotificationRule,
    IncidentPriority,
    IncidentResponder,
    IncidentStakeholder,
    MaintenanceWindowScope,
    CalendarFeed,
    NotificationPolicy,
    NotificationPolicyRule,
    NotificationPolicyRuleChannel,
    PriorityPolicy,
    PriorityPolicyRule,
    MatcherPreset,
)


CLEANUP_MODELS = [
    AlertNotificationEvent,
    AlertNotification,
    AlertEvent,
    AlertComment,
    AlertGroupMerge,
    BrowserPushActionToken,
    BrowserPushSubscription,
    UserNotificationDelivery,
    UserNotificationRule,
    IncidentResponder,
    IncidentStakeholder,
    Silence,
    AlertRouteChannel,
    Alert,
    AlertGroup,
    NotificationPolicyRuleChannel,
    NotificationPolicyRule,
    PriorityPolicyRule,
    PriorityPolicy,
    ServiceMatchRule,
    ServiceChannel,
    ServiceDependency,
    ServiceLink,
    ServiceRunbook,
    ServiceSlo,
    ServiceStatusHistory,
    MaintenanceWindowScope,
    MaintenanceWindowService,
    MaintenanceWindow,
    AlertRoute,
    ServiceRunbook,
    MatcherPreset,
    Service,
    NotificationPolicy,
    NotificationChannel,
    OnCallShiftEmailNotification,
    RotationLayerRestriction,
    RotationLayerMember,
    RotationLayer,
    RotationOverride,
    RotationMember,
    Rotation,
    TeamUser,
    CalendarFeed,
    UserGroup,
    UserRole,
    AuditLog,
    ApiToken,
    AppLock,
    Role,
    User,
    SsoIdentity,
    SsoGroupMapping,
    SsoProvider,
    EscalationPolicyRule,
    EscalationPolicy,
    Team,
    Group,
    IncidentPriority,
]


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)

    if TEST_DB.exists():
        TEST_DB.unlink()

    db = init_database()
    db.connect(reuse_if_open=True)
    migrate()
    db.close()

    yield

    db = init_database()
    if not db.is_closed():
        db.close()


@pytest.fixture(autouse=True)
def clean_database(migrated_database):
    db = init_database()
    db.connect(reuse_if_open=True)

    for model in CLEANUP_MODELS:
        if db.table_exists(model._meta.table_name):
            model.delete().execute()

    yield

    if db.is_closed():
        db.connect(reuse_if_open=True)

    for model in CLEANUP_MODELS:
        if db.table_exists(model._meta.table_name):
            model.delete().execute()

    if not db.is_closed():
        db.close()


@pytest.fixture
def db(migrated_database):
    db = init_database()
    db.connect(reuse_if_open=True)
    yield db
    if not db.is_closed():
        db.close()


@pytest.fixture
def app(migrated_database):
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(db):
    return create_user(
        username="admin",
        email="admin@example.com",
        is_admin=True,
    )


@pytest.fixture
def admin_headers(admin_user):
    token, _ = create_access_token(admin_user)

    return {
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture
def auth_headers(admin_headers):
    return admin_headers
