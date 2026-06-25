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
    DeferredForeignKey,
)

from app.db import database_proxy


class JSONTextField(TextField):
    """Store JSON-compatible values in a portable text field."""

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
    """Base model for all tables."""

    class Meta:
        database = database_proxy


class SoftDeleteModel(BaseModel):
    """Base model for soft-deletable resources."""

    deleted = BooleanField(default=False, index=True)
    deleted_at = DateTimeField(null=True)


class Migration(BaseModel):
    """Applied migration record."""

    id = AutoField()
    name = CharField(unique=True)
    applied_at = DateTimeField(default=datetime.utcnow)


class MigrationState(BaseModel):
    """Legacy migration state record kept for backward compatibility."""

    id = AutoField()
    version = IntegerField(unique=True)
    name = CharField()
    service_version = CharField(null=True)
    applied_at = DateTimeField(default=datetime.utcnow)


class Group(SoftDeleteModel):
    """Access boundary for all resources."""

    id = AutoField()
    slug = CharField(unique=True)
    name = CharField()
    description = TextField(null=True)
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "oncall_group"


class Team(SoftDeleteModel):
    """Independent on-call team inside a group."""

    id = AutoField()
    group = ForeignKeyField(Group, null=True, backref="teams", on_delete="CASCADE")
    slug = CharField(unique=True)
    name = CharField()
    description = TextField(null=True)
    escalation_enabled = BooleanField(default=True)
    escalation_after_reminders = IntegerField(default=2)
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)


class MatcherPreset(SoftDeleteModel):
    """Reusable alert matcher owned by a team."""

    id = AutoField()

    team = ForeignKeyField(
        Team,
        backref="matcher",
        on_delete="CASCADE",
    )

    name = CharField()
    description = TextField(null=True)
    matchers = JSONTextField(default=dict)

    enabled = BooleanField(default=True, index=True)
    version = IntegerField(default=1)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "matcher_preset"
        indexes = (
            (("team", "name"), True),
            (("team", "enabled"), False),
        )


class User(SoftDeleteModel):
    """On-call user."""

    id = AutoField()
    username = CharField(unique=True)
    display_name = CharField(null=True)
    email = CharField(null=True)
    phone = CharField(null=True)
    timezone = CharField(null=True)
    telegram_user_id = CharField(null=True)
    slack_user_id = CharField(null=True)
    mattermost_user_id = CharField(null=True)
    notify_oncall_shift_start_email = BooleanField(default=True)
    notify_oncall_shift_end_email = BooleanField(default=True)
    password_hash = CharField(null=True)
    active = BooleanField(default=True)
    is_admin = BooleanField(default=False)
    active_group = ForeignKeyField(Group, null=True, backref="active_users", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)


class UserGroup(BaseModel):
    """User membership in a group.

    Role values:
    - viewer: can see group-scoped data;
    - editor: can create/edit group-level operational resources;
    - user_admin: can create and manage users only inside this group boundary.
    """

    id = AutoField()
    user = ForeignKeyField(User, backref="group_memberships", on_delete="CASCADE")
    group = ForeignKeyField(Group, backref="user_memberships", on_delete="CASCADE")
    role = CharField(default="viewer")
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("user", "group"), True),
        )


class Role(BaseModel):
    """RBAC role placeholder."""

    id = AutoField()
    name = CharField(unique=True)
    description = TextField(null=True)
    permissions = JSONTextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)


class UserRole(BaseModel):
    """RBAC user role assignment placeholder."""

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
    """Membership between teams and users.

    Role values:
    - viewer: can see team resources;
    - responder: can see team resources and ack/resolve alerts;
    - manager: can manage team resources and team membership.
    """

    id = AutoField()
    team = ForeignKeyField(Team, backref="memberships", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="team_memberships", on_delete="CASCADE")
    role = CharField(default="viewer")
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("team", "user"), True),
        )


class Rotation(SoftDeleteModel):
    """On-call rotation for a specific team."""

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
        table_name = "rotation"


class RotationMember(BaseModel):
    """User position inside a rotation."""

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
    """Temporary override for a rotation."""

    id = AutoField()
    rotation = ForeignKeyField(Rotation, backref="overrides", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="rotation_overrides", on_delete="CASCADE")
    starts_at = DateTimeField()
    ends_at = DateTimeField()
    reason = TextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)


class NotificationChannel(SoftDeleteModel):
    """Notification target."""

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


class EscalationPolicy(SoftDeleteModel):
    """Escalation policy for a team."""

    id = AutoField()
    team = ForeignKeyField(Team, backref="escalation_policies", on_delete="CASCADE")
    name = CharField()
    description = TextField(null=True)
    enabled = BooleanField(default=True)
    repeat_count = IntegerField(default=0)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "escalation_policy"
        indexes = (
            (("team", "name"), True),
        )


class EscalationPolicyRule(BaseModel):
    """One escalation policy level."""

    id = AutoField()
    policy = ForeignKeyField(EscalationPolicy, backref="rules", on_delete="CASCADE")
    position = IntegerField()
    delay_seconds = IntegerField(default=300)
    target_type = CharField()
    target_rotation = ForeignKeyField(
        Rotation,
        null=True,
        backref="escalation_policy_rules",
        on_delete="SET NULL",
    )
    target_user = ForeignKeyField(
        User,
        null=True,
        backref="escalation_policy_rules",
        on_delete="SET NULL",
    )
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "escalation_policy_rule"
        indexes = (
            (("policy", "position"), True),
            (("policy", "enabled"), False),
        )


class NotificationPolicy(SoftDeleteModel):
    """Reusable channel selection policy for services."""

    id = AutoField()

    team = ForeignKeyField(
        Team,
        backref="notification_policies",
        on_delete="CASCADE",
    )

    name = CharField()
    description = TextField(null=True)
    enabled = BooleanField(default=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "notification_policy"
        indexes = (
            (("team", "name"), True),
            (("team", "enabled"), False),
        )


class NotificationPolicyRule(SoftDeleteModel):
    """One ordered notification policy rule."""

    id = AutoField()

    policy = ForeignKeyField(
        NotificationPolicy,
        backref="rules",
        on_delete="CASCADE",
    )

    name = CharField()
    description = TextField(null=True)

    position = IntegerField(default=0)

    event_types = JSONTextField(null=True)
    matchers = JSONTextField(null=True)
    matcher_preset = ForeignKeyField(
        MatcherPreset,
        null=True,
        backref="notification_policy_rules",
        on_delete="RESTRICT",
    )

    continue_matching = BooleanField(default=False)
    enabled = BooleanField(default=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "notification_policy_rule"
        indexes = (
            (("policy", "position"), False),
            (("policy", "enabled"), False),
        )


class NotificationPolicyRuleChannel(BaseModel):
    """Link a notification policy rule to a channel."""

    id = AutoField()

    rule = ForeignKeyField(
        NotificationPolicyRule,
        backref="rule_channels",
        on_delete="CASCADE",
    )

    channel = ForeignKeyField(
        NotificationChannel,
        backref="notification_policy_rules",
        on_delete="CASCADE",
    )

    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "notification_policy_rule_channel"
        indexes = (
            (("rule", "channel"), True),
        )


class Service(SoftDeleteModel):
    """Technical service or system affected by alerts."""

    id = AutoField()
    group = ForeignKeyField(Group, null=True, backref="services", on_delete="CASCADE")
    team = ForeignKeyField(Team, backref="services", on_delete="CASCADE")

    slug = CharField()
    name = CharField()
    description = TextField(null=True)

    service_type = CharField(default="other")
    environment = CharField(default="production")
    criticality = CharField(default="medium")
    tier = CharField(default="tier_3")

    status = CharField(default="operational")
    status_source = CharField(default="manual")
    status_message = TextField(null=True)
    status_updated_at = DateTimeField(null=True)
    status_updated_by = ForeignKeyField(
        User,
        null=True,
        backref="service_status_updates",
        on_delete="SET NULL",
    )

    default_rotation = ForeignKeyField(
        Rotation,
        null=True,
        backref="default_for_services",
        on_delete="SET NULL",
    )
    default_escalation_policy = ForeignKeyField(
        EscalationPolicy,
        null=True,
        backref="default_for_services",
        on_delete="SET NULL",
    )
    priority_policy = DeferredForeignKey(
        "PriorityPolicy",
        null=True,
        backref="services",
        on_delete="SET NULL",
    )
    notification_policy = ForeignKeyField(
        NotificationPolicy,
        null=True,
        backref="services",
        on_delete="SET NULL",
    )

    labels = JSONTextField(null=True)
    tags = JSONTextField(null=True)
    metadata = JSONTextField(null=True)

    enabled = BooleanField(default=True)
    public = BooleanField(default=False)
    public_name = CharField(null=True)
    public_description = TextField(null=True)
    public_order = IntegerField(default=100)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service"
        indexes = (
            (("team", "slug"), True),
            (("team", "status"), False),
            (("group", "enabled"), False),
        )


class ServiceChannel(BaseModel):
    """Default notification channel for a service."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="service_channels", on_delete="CASCADE")
    channel = ForeignKeyField(
        NotificationChannel,
        backref="service_channels",
        on_delete="CASCADE",
    )
    purpose = CharField(default="default")
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_channel"
        indexes = (
            (("service", "channel", "purpose"), True),
        )


class ServiceDependency(SoftDeleteModel):
    """Dependency between two technical services."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="dependencies", on_delete="CASCADE")
    depends_on_service = ForeignKeyField(
        Service,
        backref="dependent_services",
        on_delete="CASCADE",
    )

    dependency_type = CharField(default="hard")
    criticality = CharField(default="important")
    description = TextField(null=True)

    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_dependency"
        indexes = (
            (("service", "depends_on_service"), True),
        )


class ServiceRunbook(SoftDeleteModel):
    """Runbook attached to a service."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="runbooks", on_delete="CASCADE")

    title = CharField()
    description = TextField(null=True)
    url = TextField()

    severity = CharField(null=True)
    matchers = JSONTextField(null=True)
    priority = IntegerField(default=100)

    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_runbook"
        indexes = (
            (("service", "priority"), False),
            (("service", "enabled"), False),
        )


class ServiceLink(SoftDeleteModel):
    """Useful service link such as dashboard, logs, repository or docs."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="links", on_delete="CASCADE")

    link_type = CharField(default="other")
    label = CharField()
    url = TextField()
    description = TextField(null=True)
    priority = IntegerField(default=100)

    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_link"
        indexes = (
            (("service", "link_type"), False),
            (("service", "priority"), False),
        )


class IncidentPriority(BaseModel):
    """Configurable incident priority."""

    id = AutoField()

    slug = CharField(unique=True, index=True)
    name = CharField()
    description = TextField(null=True)

    level = IntegerField(index=True)
    color = CharField(null=True)

    enabled = BooleanField(default=True, index=True)
    default = BooleanField(default=False, index=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "incident_priority"
        indexes = (
            (("level", "enabled"), False),
        )


class PriorityPolicy(SoftDeleteModel):
    """Automatic incident priority policy owned by a team."""

    id = AutoField()

    team = ForeignKeyField(
        Team,
        backref="priority_policies",
        on_delete="CASCADE",
    )

    name = CharField()
    description = TextField(null=True)

    enabled = BooleanField(default=True, index=True)
    default_for_team = BooleanField(default=False, index=True)

    update_mode = CharField(default="raise_only")
    source_priority_mode = CharField(default="ignore")
    fallback_mode = CharField(default="severity_mapping")

    fallback_priority = ForeignKeyField(
        IncidentPriority,
        null=True,
        backref="fallback_for_priority_policies",
        on_delete="SET NULL",
    )

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "priority_policy"
        indexes = (
            (("team", "name"), True),
            (("team", "enabled"), False),
            (("team", "default_for_team"), False),
        )


class PriorityPolicyRule(SoftDeleteModel):
    """One ordered priority resolution rule."""

    id = AutoField()

    policy = ForeignKeyField(
        PriorityPolicy,
        backref="rules",
        on_delete="CASCADE",
    )

    name = CharField()
    description = TextField(null=True)
    position = IntegerField()

    matchers = JSONTextField(default=dict)
    matcher_preset = ForeignKeyField(
        MatcherPreset,
        null=True,
        backref="priority_policy_rules",
        on_delete="RESTRICT",
    )

    priority = ForeignKeyField(
        IncidentPriority,
        backref="priority_policy_rules",
        on_delete="RESTRICT",
    )

    enabled = BooleanField(default=True, index=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "priority_policy_rule"
        indexes = (
            (("policy", "position"), False),
            (("policy", "enabled"), False),
        )


class ServiceOwner(BaseModel):
    """Additional service owner or stakeholder."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="owners", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="service_ownerships", on_delete="CASCADE")
    role = CharField(default="owner")
    active = BooleanField(default=True)
    notify_on_created = BooleanField(default=True)
    notify_on_priority_change = BooleanField(default=True)
    notify_on_status_change = BooleanField(default=True)
    notify_on_resolved = BooleanField(default=True)
    notify_on_comment = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_owner"
        indexes = (
            (("service", "user", "role"), True),
        )


class ServiceSlo(SoftDeleteModel):
    """Service-level targets for acknowledgement and resolution."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="slos", on_delete="CASCADE")

    name = CharField()
    description = TextField(null=True)
    severity = CharField(null=True)

    ack_target_seconds = IntegerField(null=True)
    resolve_target_seconds = IntegerField(null=True)
    availability_target_basis_points = IntegerField(null=True)

    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_slo"
        indexes = (
            (("service", "name"), True),
            (("service", "enabled"), False),
        )


class AlertRoute(SoftDeleteModel):
    """Route incoming alerts to a team, rotation and channels."""

    id = AutoField()
    team = ForeignKeyField(Team, backref="alert_routes", on_delete="CASCADE")
    name = CharField()
    source = CharField()
    rotation = ForeignKeyField(Rotation, backref="alert_routes", null=True, on_delete="SET NULL")
    escalation_policy = ForeignKeyField(
        EscalationPolicy,
        backref="alert_routes",
        null=True,
        on_delete="SET NULL",
    )
    matcher_preset = ForeignKeyField(
        MatcherPreset,
        null=True,
        backref="alert_routes",
        on_delete="RESTRICT",
    )
    matchers = JSONTextField(null=True)
    group_by = JSONTextField(null=True)
    integration_config = JSONTextField(null=True)
    notification_channel_mode = CharField(
        default="route_only",
        index=True,
    )
    intake_token_prefix = CharField(null=True, index=True)
    intake_token_hash = CharField(null=True)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    service = ForeignKeyField(
        Service,
        null=True,
        backref="alert_routes",
        on_delete="SET NULL",
    )

    class Meta:
        indexes = (
            (("team", "name"), True),
        )


class MaintenanceWindow(SoftDeleteModel):
    """Planned maintenance window."""

    id = AutoField()

    group = ForeignKeyField(
        Group,
        null=True,
        backref="maintenance_windows",
        on_delete="CASCADE",
    )
    team = ForeignKeyField(
        Team,
        null=True,
        backref="maintenance_windows",
        on_delete="CASCADE",
    )

    name = CharField()
    description = TextField(null=True)

    starts_at = DateTimeField()
    ends_at = DateTimeField()

    timezone = CharField(default="UTC")
    rrule = TextField(null=True)

    behavior = CharField(default="suppress_notifications", index=True)
    status = CharField(default="scheduled", index=True)

    enabled = BooleanField(default=True, index=True)

    created_by = ForeignKeyField(
        User,
        null=True,
        backref="created_maintenance_windows",
        on_delete="SET NULL",
    )

    cancelled_by = ForeignKeyField(
        User,
        null=True,
        backref="cancelled_maintenance_windows",
        on_delete="SET NULL",
    )
    cancelled_at = DateTimeField(null=True)
    cancel_reason = TextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "maintenance_window"
        indexes = (
            (("team", "starts_at"), False),
            (("group", "starts_at"), False),
            (("status", "enabled"), False),
            (("starts_at", "ends_at"), False),
        )


class MaintenanceWindowService(BaseModel):
    """Legacy link maintenance window to affected services."""

    id = AutoField()

    maintenance_window = ForeignKeyField(
        MaintenanceWindow,
        backref="service_links",
        on_delete="CASCADE",
    )
    service = ForeignKeyField(
        Service,
        backref="maintenance_windows",
        on_delete="CASCADE",
    )

    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "maintenance_window_service"
        indexes = (
            (("maintenance_window", "service"), True),
        )


class MaintenanceWindowScope(BaseModel):
    """Target scope for a maintenance window."""

    id = AutoField()

    maintenance_window = ForeignKeyField(
        MaintenanceWindow,
        backref="scopes",
        on_delete="CASCADE",
    )

    scope_type = CharField(index=True)
    group = ForeignKeyField(
        Group,
        null=True,
        backref="maintenance_window_scopes",
        on_delete="CASCADE",
    )
    team = ForeignKeyField(
        Team,
        null=True,
        backref="maintenance_window_scopes",
        on_delete="CASCADE",
    )
    service = ForeignKeyField(
        Service,
        null=True,
        backref="maintenance_window_scopes",
        on_delete="CASCADE",
    )
    route = ForeignKeyField(
        AlertRoute,
        null=True,
        backref="maintenance_window_scopes",
        on_delete="CASCADE",
    )

    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "maintenance_window_scope"
        indexes = (
            (("maintenance_window", "scope_type"), False),
            (("group", "scope_type"), False),
            (("team", "scope_type"), False),
            (("service", "scope_type"), False),
            (("route", "scope_type"), False),
        )


class ServiceMatchRule(SoftDeleteModel):
    """Map alerts to affected services after an alert route has matched."""

    id = AutoField()
    team = ForeignKeyField(Team, backref="service_match_rules", on_delete="CASCADE")
    route = ForeignKeyField(
        AlertRoute,
        null=True,
        backref="service_match_rules",
        on_delete="CASCADE",
    )
    service = ForeignKeyField(Service, backref="match_rules", on_delete="CASCADE")

    position = IntegerField(default=0)
    name = CharField()
    description = TextField(null=True)
    matcher_preset = ForeignKeyField(
        MatcherPreset,
        null=True,
        backref="service_match_rules",
        on_delete="RESTRICT",
    )
    matchers = JSONTextField(null=True)

    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_match_rule"
        indexes = (
            (("route", "position"), False),
            (("team", "position"), False),
            (("service", "enabled"), False),
        )


class AlertRouteChannel(BaseModel):
    """Link an alert route to notification channels."""

    id = AutoField()
    route = ForeignKeyField(AlertRoute, backref="route_channels", on_delete="CASCADE")
    channel = ForeignKeyField(NotificationChannel, backref="channel_routes", on_delete="CASCADE")

    class Meta:
        indexes = (
            (("route", "channel"), True),
        )


class AlertGroup(BaseModel):
    """Logical incident/group containing one or more concrete alerts."""

    id = AutoField()

    team = ForeignKeyField(Team, null=True, backref="alert_groups", on_delete="SET NULL")
    route = ForeignKeyField(AlertRoute, null=True, backref="alert_groups", on_delete="SET NULL")
    service = ForeignKeyField(Service, null=True, backref="alert_groups", on_delete="SET NULL")
    rotation = ForeignKeyField(Rotation, null=True, backref="alert_groups", on_delete="SET NULL")

    escalation_policy = ForeignKeyField(
        EscalationPolicy,
        null=True,
        backref="alert_groups",
        on_delete="SET NULL",
    )
    escalation_rule = ForeignKeyField(
        EscalationPolicyRule,
        null=True,
        backref="alert_groups",
        on_delete="SET NULL",
    )

    next_escalation_at = DateTimeField(null=True, index=True)
    last_escalated_at = DateTimeField(null=True)
    escalation_repeat_count = IntegerField(default=0)
    escalation_level = IntegerField(default=0)

    assignee = ForeignKeyField(User, null=True, backref="assigned_alert_groups", on_delete="SET NULL")

    source = CharField()
    group_key_hash = CharField(index=True)
    group_key = TextField()

    title = CharField()
    message = TextField(null=True)
    severity = CharField(null=True)

    common_labels = JSONTextField(null=True)
    label_values = JSONTextField(null=True)
    payload_summary = JSONTextField(null=True)

    status = CharField(default="firing", index=True)
    previous_status = CharField(null=True)

    acknowledged_by = ForeignKeyField(
        User,
        null=True,
        backref="acknowledged_alert_groups",
        on_delete="SET NULL",
    )
    acknowledged_at = DateTimeField(null=True)

    resolved_by = ForeignKeyField(
        User,
        null=True,
        backref="resolved_alert_groups",
        on_delete="SET NULL",
    )
    resolved_at = DateTimeField(null=True)

    first_seen_at = DateTimeField(default=datetime.utcnow)
    last_seen_at = DateTimeField(default=datetime.utcnow)
    last_notification_at = DateTimeField(null=True)
    notification_due_at = DateTimeField(null=True, index=True)
    notification_pending = BooleanField(default=False, index=True)
    notification_reason = CharField(null=True)

    alert_count = IntegerField(default=0)
    firing_count = IntegerField(default=0)
    acknowledged_count = IntegerField(default=0)
    resolved_count = IntegerField(default=0)
    silenced_count = IntegerField(default=0)

    reminder_count = IntegerField(default=0)
    silenced = BooleanField(default=False)

    merged_into = ForeignKeyField(
        "self",
        null=True,
        backref="merged_groups",
        on_delete="SET NULL",
    )
    merged_by = ForeignKeyField(
        User,
        null=True,
        backref="merged_alert_groups",
        on_delete="SET NULL",
    )
    merged_at = DateTimeField(null=True)
    merge_reason = TextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    priority = ForeignKeyField(
        IncidentPriority,
        null=True,
        backref="alert_groups",
        on_delete="SET NULL",
    )

    priority_slug = CharField(default="p3", index=True)
    priority_order = IntegerField(default=3, index=True)
    priority_set_manually = BooleanField(default=False, index=True)

    priority_set_by = ForeignKeyField(
        User,
        null=True,
        backref="priority_changes",
        on_delete="SET NULL",
    )

    priority_set_at = DateTimeField(null=True)

    maintenance_window = ForeignKeyField(
        MaintenanceWindow,
        null=True,
        backref="alert_groups",
        on_delete="SET NULL",
    )

    maintenance_behavior = CharField(null=True)
    maintenance_suppressed = BooleanField(default=False, index=True)

    class Meta:
        table_name = "alert_group"
        indexes = (
            (("team", "status"), False),
            (("source", "group_key_hash", "status"), False),
            (("route", "status"), False),
            (("service", "status"), False),
            (("merged_into",), False),
        )


class Alert(BaseModel):
    """Alert stored after normalization and routing."""

    id = AutoField()
    team = ForeignKeyField(Team, null=True, backref="alerts", on_delete="SET NULL")
    route = ForeignKeyField(AlertRoute, null=True, backref="alerts", on_delete="SET NULL")
    rotation = ForeignKeyField(Rotation, null=True, backref="alerts", on_delete="SET NULL")
    escalation_policy = ForeignKeyField(
        EscalationPolicy,
        null=True,
        backref="alerts",
        on_delete="SET NULL",
    )
    escalation_rule = ForeignKeyField(
        EscalationPolicyRule,
        null=True,
        backref="alerts",
        on_delete="SET NULL",
    )
    next_escalation_at = DateTimeField(null=True, index=True)
    last_escalated_at = DateTimeField(null=True)
    escalation_repeat_count = IntegerField(default=0)
    assignee = ForeignKeyField(User, null=True, backref="assigned_alerts", on_delete="SET NULL")
    source = CharField()
    external_id = CharField(null=True)
    dedup_key = CharField(index=True)
    group_key = CharField(index=True)
    title = CharField()
    message = TextField(null=True)
    severity = CharField(null=True)
    priority = ForeignKeyField(
        IncidentPriority,
        null=True,
        backref="alerts",
        on_delete="SET NULL",
    )

    priority_slug = CharField(default="p3", index=True)
    priority_order = IntegerField(default=3, index=True)

    maintenance_window = ForeignKeyField(
        MaintenanceWindow,
        null=True,
        backref="alerts",
        on_delete="SET NULL",
    )

    maintenance_behavior = CharField(null=True)
    maintenance_suppressed = BooleanField(default=False, index=True)
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
    resolved_at = DateTimeField(null=True)
    service = ForeignKeyField(Service, null=True, backref="alerts", on_delete="SET NULL")
    group = ForeignKeyField(
        AlertGroup,
        null=True,
        backref="alerts",
        on_delete="SET NULL",
    )

    class Meta:
        indexes = (
            (("team", "status"), False),
            (("source", "dedup_key"), False),
            (("group_key", "status"), False),
        )


class AlertComment(BaseModel):
    """Human comment attached to an alert group or concrete alert."""

    id = AutoField()

    group = ForeignKeyField(
        AlertGroup,
        null=True,
        backref="comments",
        on_delete="CASCADE",
    )
    alert = ForeignKeyField(
        Alert,
        null=True,
        backref="comments",
        on_delete="CASCADE",
    )

    user = ForeignKeyField(
        User,
        null=True,
        backref="alert_comments",
        on_delete="SET NULL",
    )

    body = TextField()

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    deleted = BooleanField(default=False, index=True)
    deleted_at = DateTimeField(null=True)

    class Meta:
        table_name = "alert_comment"
        indexes = (
            (("group", "created_at"), False),
            (("alert", "created_at"), False),
            (("user", "created_at"), False),
        )


class IncidentResponder(BaseModel):
    """Responder request attached to an incident / alert group."""

    id = AutoField()

    group = ForeignKeyField(
        AlertGroup,
        backref="incident_responders",
        on_delete="CASCADE",
    )

    target_type = CharField(index=True)

    target_user = ForeignKeyField(
        User,
        null=True,
        backref="incident_responder_requests",
        on_delete="SET NULL",
    )
    target_team = ForeignKeyField(
        Team,
        null=True,
        backref="incident_responder_requests",
        on_delete="SET NULL",
    )
    target_rotation = ForeignKeyField(
        Rotation,
        null=True,
        backref="incident_responder_requests",
        on_delete="SET NULL",
    )
    target_escalation_policy = ForeignKeyField(
        EscalationPolicy,
        null=True,
        backref="incident_responder_requests",
        on_delete="SET NULL",
    )

    requested_by = ForeignKeyField(
        User,
        null=True,
        backref="requested_incident_responders",
        on_delete="SET NULL",
    )

    accepted_by = ForeignKeyField(
        User,
        null=True,
        backref="accepted_incident_responder_requests",
        on_delete="SET NULL",
    )

    declined_by = ForeignKeyField(
        User,
        null=True,
        backref="declined_incident_responder_requests",
        on_delete="SET NULL",
    )

    status = CharField(default="requested", index=True)

    message = TextField(null=True)
    response_message = TextField(null=True)

    notification_status = CharField(default="pending", index=True)
    notification_error = TextField(null=True)

    requested_at = DateTimeField(default=datetime.utcnow)
    responded_at = DateTimeField(null=True)
    expires_at = DateTimeField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "incident_responder"
        indexes = (
            (("group", "status"), False),
            (("target_user", "status"), False),
            (("target_team", "status"), False),
            (("target_rotation", "status"), False),
            (("target_escalation_policy", "status"), False),
        )


class IncidentStakeholder(BaseModel):
    """Stakeholder subscribed to incident updates."""

    id = AutoField()

    group = ForeignKeyField(
        AlertGroup,
        backref="incident_stakeholders",
        on_delete="CASCADE",
    )

    user = ForeignKeyField(
        User,
        null=True,
        backref="incident_stakeholder_subscriptions",
        on_delete="SET NULL",
    )

    email = CharField(null=True)
    display_name = CharField(null=True)

    role = CharField(default="stakeholder", index=True)
    source = CharField(default="manual", index=True)

    notify_on_created = BooleanField(default=True)
    notify_on_priority_change = BooleanField(default=True)
    notify_on_status_change = BooleanField(default=True)
    notify_on_resolved = BooleanField(default=True)
    notify_on_comment = BooleanField(default=True)

    active = BooleanField(default=True, index=True)

    created_by = ForeignKeyField(
        User,
        null=True,
        backref="created_incident_stakeholders",
        on_delete="SET NULL",
    )

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "incident_stakeholder"
        indexes = (
            (("group", "user"), False),
            (("group", "email"), False),
            (("group", "role"), False),
            (("group", "active"), False),
        )


class ServiceStatusHistory(BaseModel):
    """Product history of service status changes."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="status_history", on_delete="CASCADE")

    old_status = CharField(null=True)
    new_status = CharField()
    source = CharField(default="manual")
    message = TextField(null=True)

    alert = ForeignKeyField(Alert, null=True, backref="service_status_changes", on_delete="SET NULL")
    maintenance_window = ForeignKeyField(
        MaintenanceWindow,
        null=True,
        backref="service_status_changes",
        on_delete="SET NULL",
    )
    changed_by = ForeignKeyField(
        User,
        null=True,
        backref="service_status_changes",
        on_delete="SET NULL",
    )

    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_status_history"
        indexes = (
            (("service", "created_at"), False),
            (("new_status", "created_at"), False),
        )


class AlertEvent(BaseModel):
    """Alert/group history event."""

    id = AutoField()
    group = ForeignKeyField(AlertGroup, null=True, backref="events", on_delete="CASCADE")
    alert = ForeignKeyField(Alert, null=True, backref="events", on_delete="CASCADE")
    event_type = CharField()
    message = TextField(null=True)
    user = ForeignKeyField(User, null=True, backref="alert_events", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)


class AlertExplainTrace(BaseModel):
    """One alert routing/execution explain trace."""

    id = AutoField()
    trace_id = CharField(unique=True, index=True)

    group = ForeignKeyField(
        AlertGroup,
        null=True,
        backref="explain_traces",
        on_delete="CASCADE",
    )
    alert = ForeignKeyField(
        Alert,
        null=True,
        backref="explain_traces",
        on_delete="CASCADE",
    )

    mode = CharField(default="live", index=True)  # live, dry_run
    source = CharField(null=True, index=True)
    dedup_key = CharField(null=True, index=True)

    status = CharField(default="running", index=True)  # running, completed, stopped, failed
    outcome = CharField(null=True, index=True)  # created, updated, suppressed, ignored, routing_failed
    reason = TextField(null=True)

    input_summary = JSONTextField(null=True)
    result = JSONTextField(null=True)

    started_at = DateTimeField(default=datetime.utcnow, index=True)
    finished_at = DateTimeField(null=True, index=True)


class AlertExplainStep(BaseModel):
    """One ordered step inside alert explain trace."""

    id = AutoField()

    trace = ForeignKeyField(
        AlertExplainTrace,
        backref="steps",
        on_delete="CASCADE",
    )

    position = IntegerField(default=0, index=True)

    stage = CharField(index=True)
    code = CharField(index=True)
    status = CharField(default="info", index=True)

    title = CharField()
    message = TextField(null=True)

    data = JSONTextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow, index=True)


class AlertGroupMerge(BaseModel):
    """Manual alert group merge history."""

    id = AutoField()
    source_group = ForeignKeyField(AlertGroup, backref="source_merges", on_delete="CASCADE")
    target_group = ForeignKeyField(AlertGroup, backref="target_merges", on_delete="CASCADE")
    merged_by = ForeignKeyField(User, null=True, backref="alert_group_merges", on_delete="SET NULL")
    reason = TextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "alert_group_merge"
        indexes = (
            (("source_group", "target_group"), False),
        )


class AlertNotification(BaseModel):
    """Delivery record for a notification sent to an external channel."""

    id = AutoField()
    group = ForeignKeyField(AlertGroup, null=True, backref="notifications", on_delete="CASCADE")
    alert = ForeignKeyField(Alert, null=True, backref="notifications", on_delete="CASCADE")
    channel = ForeignKeyField(NotificationChannel, backref="notifications", on_delete="CASCADE")
    provider = CharField()
    external_message_id = CharField(null=True)
    external_channel_id = CharField(null=True)
    last_event_type = CharField(null=True)
    last_error = TextField(null=True)
    provider_status = CharField(null=True)
    provider_payload = JSONTextField(null=True)
    last_callback_at = DateTimeField(null=True)
    callback_count = IntegerField(default=0)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("group", "channel"), True),
            (("channel", "external_message_id"), False),
        )


class AlertNotificationEvent(BaseModel):
    """Provider callback history for a notification delivery."""

    id = AutoField()
    notification = ForeignKeyField(
        AlertNotification,
        backref="callback_events",
        on_delete="CASCADE",
    )
    event_type = CharField()
    provider_status = CharField(null=True)
    digit = CharField(null=True)
    action = CharField(null=True)
    message = TextField(null=True)
    payload = JSONTextField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (("notification", "created_at"), False),
        )


class OnCallShiftEmailNotification(BaseModel):
    """Deduplication log for on-call shift start/end email notifications."""

    id = AutoField()

    user = ForeignKeyField(User, backref="oncall_shift_email_notifications", on_delete="CASCADE")
    rotation = ForeignKeyField(Rotation, backref="oncall_shift_email_notifications", on_delete="CASCADE")

    event_type = CharField(index=True)  # shift_start | shift_end

    slot_start_at = DateTimeField(index=True)
    slot_end_at = DateTimeField(index=True)

    layer_id = IntegerField(null=True)
    override_id = IntegerField(null=True)

    fingerprint = CharField(unique=True, index=True)

    status = CharField(default="pending", index=True)  # pending | sent | failed | skipped
    last_error = TextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    sent_at = DateTimeField(null=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "oncall_shift_email_notification"
        indexes = (
            (("user", "event_type", "slot_start_at", "slot_end_at"), False),
            (("rotation", "event_type", "slot_start_at"), False),
        )


class Silence(SoftDeleteModel):
    """Alert silence rule for a team."""

    id = AutoField()
    team = ForeignKeyField(Team, backref="silences", on_delete="CASCADE")
    name = CharField()
    reason = TextField(null=True)
    matcher_preset = ForeignKeyField(
        MatcherPreset,
        null=True,
        backref="silences",
        on_delete="RESTRICT",
    )
    matchers = JSONTextField(null=True)
    starts_at = DateTimeField()
    ends_at = DateTimeField()
    created_by = ForeignKeyField(User, null=True, backref="created_silences", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)
    enabled = BooleanField(default=True)


class ApiToken(SoftDeleteModel):
    """Hashed API token."""

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


class SsoProvider(SoftDeleteModel):
    """SSO provider configuration for OIDC or SAML."""

    id = AutoField()
    slug = CharField(unique=True)
    label = CharField()
    protocol = CharField(default="oidc", index=True)  # oidc | saml
    enabled = BooleanField(default=True)

    # Common mapping options
    subject_claim = CharField(default="sub")
    email_claim = CharField(default="email")
    username_claim = CharField(default="preferred_username")
    display_name_claim = CharField(default="name")
    groups_claim = CharField(default="groups")
    phone_claim = CharField(default="mobile")

    allowed_domains = JSONTextField(null=True)

    auto_create_users = BooleanField(default=False)
    auto_link_by_email = BooleanField(default=True)
    require_verified_email = BooleanField(default=True)

    sync_group_memberships = BooleanField(default=True)
    remove_missing_group_memberships = BooleanField(default=False)

    # OIDC
    client_id = CharField(null=True)
    client_secret_encrypted = TextField(null=True)
    oidc_metadata_url = TextField(null=True)
    oidc_issuer = TextField(null=True)
    oidc_authorization_endpoint = TextField(null=True)
    oidc_token_endpoint = TextField(null=True)
    oidc_userinfo_endpoint = TextField(null=True)
    oidc_jwks_uri = TextField(null=True)
    oidc_scope = CharField(default="openid email profile")

    # SAML IdP
    saml_idp_entity_id = TextField(null=True)
    saml_idp_sso_url = TextField(null=True)
    saml_idp_slo_url = TextField(null=True)
    saml_idp_x509_cert = TextField(null=True)
    saml_idp_metadata_url = CharField(null=True, max_length=2048)

    # SAML SP
    saml_sp_entity_id = TextField(null=True)
    saml_sp_acs_url = TextField(null=True)
    saml_sp_sls_url = TextField(null=True)
    saml_sp_x509_cert = TextField(null=True)
    saml_sp_private_key_encrypted = TextField(null=True)
    saml_name_id_format = TextField(
        default="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
    )

    extra_config = JSONTextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "sso_provider"


class SsoIdentity(BaseModel):
    """External SSO identity linked to local IncidentRelay user."""

    id = AutoField()
    user = ForeignKeyField(User, backref="sso_identities", on_delete="CASCADE")
    provider = ForeignKeyField(SsoProvider, backref="identities", on_delete="CASCADE")

    subject = CharField()
    email = CharField(null=True)
    username = CharField(null=True)

    raw_claims = JSONTextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    last_login_at = DateTimeField(null=True)

    class Meta:
        table_name = "sso_identity"
        indexes = (
            (("provider", "subject"), True),
        )


class SsoGroupMapping(BaseModel):
    """Map external SSO group value to IncidentRelay group role."""

    id = AutoField()
    provider = ForeignKeyField(SsoProvider, backref="group_mappings", on_delete="CASCADE")

    external_group = CharField()
    incidentrelay_group = ForeignKeyField(
        Group,
        backref="sso_group_mappings",
        on_delete="CASCADE",
    )

    group_role = CharField(default="viewer")
    active = BooleanField(default=True)
    priority = IntegerField(default=100)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "sso_group_mapping"
        indexes = (
            (("provider", "external_group", "incidentrelay_group"), True),
        )


class AuditLog(BaseModel):
    """Audit log entry for API actions."""

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
    """Distributed application lock stored in the database."""

    id = AutoField()
    name = CharField(unique=True)
    owner = CharField()
    expires_at = DateTimeField()
    updated_at = DateTimeField(default=datetime.utcnow)


class RotationLayer(SoftDeleteModel):
    """Schedule layer inside a rotation.

    Rotation stays the route-facing object.
    Layers define competing/overriding schedules inside it.
    Higher priority wins.
    """

    id = AutoField()
    rotation = ForeignKeyField(Rotation, backref="layers", on_delete="CASCADE")
    name = CharField()
    description = TextField(null=True)

    priority = IntegerField(default=0, index=True)

    start_at = DateTimeField(null=True)
    duration_seconds = IntegerField(null=True)

    rotation_type = CharField(null=True)
    interval_value = IntegerField(null=True)
    interval_unit = CharField(null=True)
    handoff_time = CharField(null=True)
    handoff_weekday = IntegerField(null=True)
    timezone = CharField(null=True)

    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "rotation_layer"
        indexes = (
            (("rotation", "priority"), False),
        )


class RotationLayerMember(BaseModel):
    """Versioned user membership inside a rotation layer."""

    id = AutoField()
    layer = ForeignKeyField(RotationLayer, backref="members", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="rotation_layer_memberships", on_delete="CASCADE")
    position = IntegerField()
    active = BooleanField(default=True)

    # Period of this membership.
    # Removing a user closes the period.
    # Re-adding the same user creates a new row.
    starts_at = DateTimeField(default=datetime.utcnow, index=True)
    ends_at = DateTimeField(null=True, index=True)

    class Meta:
        table_name = "rotation_layer_member"
        indexes = (
            (("layer", "position", "starts_at"), False),
            (("layer", "user", "starts_at"), False),
            (("layer", "starts_at", "ends_at"), False),
        )


class RotationLayerRestriction(BaseModel):
    """Local-time active window for a rotation layer.

    weekday: 0=Monday ... 6=Sunday, null means every day.
    start_time/end_time are local to the layer timezone or rotation timezone.
    """

    id = AutoField()
    layer = ForeignKeyField(RotationLayer, backref="restrictions", on_delete="CASCADE")
    weekday = IntegerField(null=True)
    start_time = CharField()
    end_time = CharField()
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "rotation_layer_restriction"
        indexes = (
            (("layer", "weekday"), False),
        )


class BrowserPushSubscription(BaseModel):
    id = AutoField()

    user = ForeignKeyField(
        User,
        backref="browser_push_subscriptions",
        on_delete="CASCADE",
    )

    endpoint = TextField(unique=True)
    p256dh = TextField()
    auth = TextField()

    device_name = CharField(max_length=255, null=True)
    user_agent = TextField(null=True)

    enabled = BooleanField(default=True)
    deleted = BooleanField(default=False)
    deleted_at = DateTimeField(null=True)

    last_seen_at = DateTimeField(null=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "browser_push_subscription"
        indexes = (
            (("user", "enabled", "deleted"), False),
        )


class BrowserPushActionToken(BaseModel):
    id = AutoField()

    user = ForeignKeyField(
        User,
        backref="browser_push_action_tokens",
        on_delete="CASCADE",
    )

    group = ForeignKeyField(
        AlertGroup,
        backref="browser_push_action_tokens",
        on_delete="CASCADE",
    )

    action = CharField(max_length=32)
    token_hash = CharField(max_length=128, unique=True)
    used_at = DateTimeField(null=True)
    expires_at = DateTimeField()
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "browser_push_action_token"
        indexes = (
            (("group", "user", "action"), False),
            (("expires_at", "used_at"), False),
        )


class UserNotificationRule(SoftDeleteModel):
    """PagerDuty-like user notification rule."""

    id = AutoField()

    user = ForeignKeyField(
        User,
        backref="notification_rules",
        on_delete="CASCADE",
    )

    position = IntegerField(default=0)
    method = CharField(index=True)
    delay_seconds = IntegerField(default=0)
    enabled = BooleanField(default=True)
    severities = JSONTextField(null=True)
    event_types = JSONTextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "user_notification_rule"
        indexes = (
            (("user", "position"), False),
            (("user", "enabled", "deleted"), False),
            (("method", "enabled"), False),
        )


class UserNotificationDelivery(BaseModel):
    """Scheduled or sent user-level notification delivery."""

    id = AutoField()

    group = ForeignKeyField(
        AlertGroup,
        backref="user_notification_deliveries",
        on_delete="CASCADE",
    )

    user = ForeignKeyField(
        User,
        backref="notification_deliveries",
        on_delete="CASCADE",
    )

    rule = ForeignKeyField(
        UserNotificationRule,
        null=True,
        backref="deliveries",
        on_delete="SET NULL",
    )

    method = CharField(index=True)
    event_type = CharField(index=True)

    status = CharField(default="pending", index=True)
    scheduled_at = DateTimeField(index=True)
    sent_at = DateTimeField(null=True)

    provider = CharField(null=True)
    external_message_id = CharField(null=True, index=True)
    external_channel_id = CharField(null=True)
    provider_status = CharField(null=True)
    provider_payload = JSONTextField(null=True)

    last_error = TextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "user_notification_delivery"
        indexes = (
            (("status", "scheduled_at"), False),
            (("group", "user", "method", "event_type"), False),
            (("rule", "group", "event_type"), False),
        )


class CalendarFeed(SoftDeleteModel):
    """Tokenized public ICS subscription feed for a team calendar."""

    id = AutoField()
    team = ForeignKeyField(Team, backref="calendar_feeds", on_delete="CASCADE")
    name = CharField(default="On-call calendar")
    token_prefix = CharField(index=True)
    token_hash = CharField()
    enabled = BooleanField(default=True)
    past_days = IntegerField(default=7)
    future_days = IntegerField(default=90)
    created_by = ForeignKeyField(
        User,
        null=True,
        backref="calendar_feeds",
        on_delete="SET NULL",
    )
    created_at = DateTimeField(default=datetime.utcnow)
    last_used_at = DateTimeField(null=True)
