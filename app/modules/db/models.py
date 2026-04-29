import json
from datetime import datetime

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    TextField,
)

from app.db import database_proxy


class JSONTextField(TextField):
    """
    Store JSON-compatible values in a portable text field.
    """

    def db_value(self, value):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def python_value(self, value):
        if value is None:
            return None

        if isinstance(value, (dict, list)):
            return value

        try:
            return json.loads(value)
        except Exception:
            return value


class BaseModel(Model):
    """
    Base model for all tables.
    """

    class Meta:
        database = database_proxy


class SoftDeleteModel(BaseModel):
    """
    Base model for soft-deletable resources.
    """

    deleted = BooleanField(default=False, index=True)
    deleted_at = DateTimeField(null=True)


class Migration(BaseModel):
    """
    Applied migration record.
    """

    id = AutoField()
    name = CharField(unique=True)
    applied_at = DateTimeField(default=datetime.utcnow)


class MigrationState(BaseModel):
    """
    Legacy migration state record kept for backward compatibility.
    """

    id = AutoField()
    version = IntegerField(unique=True)
    name = CharField()
    service_version = CharField(null=True)
    applied_at = DateTimeField(default=datetime.utcnow)


class Version(BaseModel):
    """
    Persisted service version.
    """

    id = AutoField()
    version = CharField(unique=True)
    updated_at = DateTimeField(default=datetime.utcnow)


class Group(SoftDeleteModel):
    """
    Access boundary for all resources.
    """

    id = AutoField()
    slug = CharField(unique=True)
    name = CharField()
    description = TextField(null=True)
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "oncall_group"


class Team(SoftDeleteModel):
    """
    Independent on-call team inside a group.
    """

    id = AutoField()
    group = ForeignKeyField(Group, null=True, backref="teams", on_delete="CASCADE")
    slug = CharField(unique=True)
    name = CharField()
    description = TextField(null=True)
    escalation_enabled = BooleanField(default=True)
    escalation_after_reminders = IntegerField(default=2)
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)


class User(SoftDeleteModel):
    """
    On-call user.
    """

    id = AutoField()
    username = CharField(unique=True)
    display_name = CharField(null=True)
    email = CharField(null=True)
    phone = CharField(null=True)
    telegram_chat_id = CharField(null=True)
    slack_user_id = CharField(null=True)
    mattermost_user_id = CharField(null=True)
    password_hash = CharField(null=True)
    active = BooleanField(default=True)
    is_admin = BooleanField(default=False)
    active_group = ForeignKeyField(Group, null=True, backref="active_users", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)


class UserGroup(BaseModel):
    """
    User membership in a group.

    role values:
    - read_only: can view resources and alerts;
    - rw: can create, edit and operate resources.
    """

    id = AutoField()
    user = ForeignKeyField(User, backref="group_memberships", on_delete="CASCADE")
    group = ForeignKeyField(Group, backref="user_memberships", on_delete="CASCADE")
    role = CharField(default="read_only")
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("user", "group"), True),
        )


class Role(BaseModel):
    """
    RBAC role placeholder.
    """

    id = AutoField()
    name = CharField(unique=True)
    description = TextField(null=True)
    permissions = JSONTextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)


class UserRole(BaseModel):
    """
    RBAC user role assignment placeholder.
    """

    id = AutoField()
    user = ForeignKeyField(User, backref="role_assignments", on_delete="CASCADE")
    role = ForeignKeyField(Role, backref="user_assignments", on_delete="CASCADE")
    team = ForeignKeyField(Team, null=True, backref="role_assignments", on_delete="CASCADE")
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("user", "role", "team"), True),
        )


class TeamUser(BaseModel):
    """
    Membership between teams and users.
    """

    id = AutoField()
    team = ForeignKeyField(Team, backref="memberships", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="team_memberships", on_delete="CASCADE")
    role = CharField(default="member")
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("team", "user"), True),
        )


class Rotation(SoftDeleteModel):
    """
    On-call rotation for a specific team.
    """

    id = AutoField()
    team = ForeignKeyField(Team, backref="rotations", on_delete="CASCADE")
    name = CharField()
    description = TextField(null=True)
    start_at = DateTimeField()
    duration_seconds = IntegerField(default=86400)
    reminder_interval_seconds = IntegerField(default=300)
    rotation_type = CharField(default="daily")
    interval_value = IntegerField(default=1)
    interval_unit = CharField(default="days")
    handoff_time = CharField(default="09:00")
    handoff_weekday = IntegerField(null=True)
    timezone = CharField(default="UTC")
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("team", "name"), True),
        )


class RotationMember(BaseModel):
    """
    User position inside a rotation.
    """

    id = AutoField()
    rotation = ForeignKeyField(Rotation, backref="members", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="rotation_memberships", on_delete="CASCADE")
    position = IntegerField()
    active = BooleanField(default=True)

    class Meta:
        indexes = (
            (("rotation", "position"), True),
            (("rotation", "user"), True),
        )


class RotationOverride(BaseModel):
    """
    Temporary override for a rotation.
    """

    id = AutoField()
    rotation = ForeignKeyField(Rotation, backref="overrides", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="rotation_overrides", on_delete="CASCADE")
    starts_at = DateTimeField()
    ends_at = DateTimeField()
    reason = TextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)


class NotificationChannel(SoftDeleteModel):
    """
    Notification target.
    """

    id = AutoField()
    group = ForeignKeyField(Group, null=True, backref="channels", on_delete="CASCADE")
    team = ForeignKeyField(Team, backref="channels", null=True, on_delete="CASCADE")
    name = CharField()
    channel_type = CharField()
    config = JSONTextField(null=True)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("team", "name"), True),
        )


class AlertRoute(SoftDeleteModel):
    """
    Route incoming alerts to a team, rotation and channels.
    """

    id = AutoField()
    team = ForeignKeyField(Team, backref="alert_routes", on_delete="CASCADE")
    name = CharField()
    source = CharField()
    rotation = ForeignKeyField(Rotation, backref="alert_routes", null=True, on_delete="SET NULL")
    matchers = JSONTextField(null=True)
    group_by = JSONTextField(null=True)
    intake_token_prefix = CharField(null=True, index=True)
    intake_token_hash = CharField(null=True)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("team", "name"), True),
        )


class AlertRouteChannel(BaseModel):
    """
    Link an alert route to notification channels.
    """

    id = AutoField()
    route = ForeignKeyField(AlertRoute, backref="route_channels", on_delete="CASCADE")
    channel = ForeignKeyField(NotificationChannel, backref="channel_routes", on_delete="CASCADE")

    class Meta:
        indexes = (
            (("route", "channel"), True),
        )


class Alert(BaseModel):
    """
    Alert stored after normalization and routing.
    """

    id = AutoField()

    team = ForeignKeyField(Team, null=True, backref="alerts", on_delete="SET NULL")
    route = ForeignKeyField(AlertRoute, null=True, backref="alerts", on_delete="SET NULL")
    rotation = ForeignKeyField(Rotation, null=True, backref="alerts", on_delete="SET NULL")
    assignee = ForeignKeyField(User, null=True, backref="assigned_alerts", on_delete="SET NULL")
    source = CharField()
    external_id = CharField(null=True)
    dedup_key = CharField(index=True)
    group_key = CharField(index=True)
    title = CharField()
    message = TextField(null=True)
    severity = CharField(null=True)
    labels = JSONTextField(null=True)
    payload = JSONTextField(null=True)
    status = CharField(default="firing")
    previous_status = CharField(null=True)
    acknowledged_by = ForeignKeyField(User, null=True, backref="acknowledged_alerts", on_delete="SET NULL")
    acknowledged_at = DateTimeField(null=True)
    first_seen_at = DateTimeField(default=datetime.utcnow)
    last_seen_at = DateTimeField(default=datetime.utcnow)
    last_notification_at = DateTimeField(null=True)
    reminder_count = IntegerField(default=0)
    escalation_level = IntegerField(default=0)
    silenced = BooleanField(default=False)

    class Meta:
        indexes = (
            (("team", "status"), False),
            (("source", "dedup_key"), False),
            (("group_key", "status"), False),
        )


class AlertEvent(BaseModel):
    """
    Alert history event.
    """

    id = AutoField()
    alert = ForeignKeyField(Alert, backref="events", on_delete="CASCADE")
    event_type = CharField()
    message = TextField(null=True)
    user = ForeignKeyField(User, null=True, backref="alert_events", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)


class AlertNotification(BaseModel):
    """
    Delivery record for a notification sent to an external channel.
    """

    id = AutoField()
    alert = ForeignKeyField(Alert, backref="notifications", on_delete="CASCADE")
    channel = ForeignKeyField(NotificationChannel, backref="notifications", on_delete="CASCADE")
    provider = CharField()
    external_message_id = CharField(null=True)
    external_channel_id = CharField(null=True)
    last_event_type = CharField(null=True)
    last_error = TextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("alert", "channel"), True),
        )


class Silence(SoftDeleteModel):
    """
    Alert silence rule for a team.
    """

    id = AutoField()
    team = ForeignKeyField(Team, backref="silences", on_delete="CASCADE")
    name = CharField()
    reason = TextField(null=True)
    matchers = JSONTextField(null=True)
    starts_at = DateTimeField()
    ends_at = DateTimeField()
    created_by = ForeignKeyField(User, null=True, backref="created_silences", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)
    enabled = BooleanField(default=True)


class ApiToken(SoftDeleteModel):
    """
    Hashed API token.
    """

    id = AutoField()
    user = ForeignKeyField(User, null=True, backref="api_tokens", on_delete="CASCADE")
    group = ForeignKeyField(Group, null=True, backref="api_tokens", on_delete="CASCADE")
    team = ForeignKeyField(Team, null=True, backref="api_tokens", on_delete="CASCADE")
    name = CharField()
    token_prefix = CharField(index=True)
    token_hash = CharField(unique=True)
    scopes = JSONTextField(null=True)
    expires_at = DateTimeField(null=True)
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    last_used_at = DateTimeField(null=True)


class AuditLog(BaseModel):
    """
    Audit log entry for API actions.
    """

    id = AutoField()
    group = ForeignKeyField(Group, null=True, backref="audit_logs", on_delete="SET NULL")
    team = ForeignKeyField(Team, null=True, backref="audit_logs", on_delete="SET NULL")
    user = ForeignKeyField(User, null=True, backref="audit_logs", on_delete="SET NULL")
    api_token = ForeignKeyField(ApiToken, null=True, backref="audit_logs", on_delete="SET NULL")
    action = CharField()
    object_type = CharField(null=True)
    object_id = IntegerField(null=True)
    message = TextField(null=True)
    data = JSONTextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)


class AppLock(BaseModel):
    """
    Distributed application lock stored in the database.
    """

    id = AutoField()
    name = CharField(unique=True)
    owner = CharField()
    expires_at = DateTimeField()
    updated_at = DateTimeField(default=datetime.utcnow)
