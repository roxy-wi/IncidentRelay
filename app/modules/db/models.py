import json
import uuid
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
    UUIDField,
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
    notify_oncall_shift_start_mattermost = BooleanField(default=True)
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
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)

    kind = CharField(default="technical")
    lifecycle = CharField(default="production")
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
    """Dependency between two services."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="dependencies", on_delete="CASCADE")
    depends_on_service = ForeignKeyField(Service, backref="dependent_services", on_delete="CASCADE")
    dependency_type = CharField(default="hard")
    criticality = CharField(default="important")
    correlation_enabled = BooleanField(default=True)
    propagation_delay_seconds = IntegerField(default=300)
    description = TextField(null=True)
    metadata = JSONTextField(default=dict)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_dependency"
        indexes = (
            (("service", "depends_on_service"), True),
            (("service", "correlation_enabled", "enabled"), False),
        )


class BusinessService(SoftDeleteModel):
    """Business-facing service shown in impact views and status pages."""

    id = AutoField()
    group = ForeignKeyField(Group, backref="business_services", on_delete="CASCADE")
    owner_team = ForeignKeyField(Team, null=True, backref="owned_business_services", on_delete="SET NULL")

    slug = CharField()
    name = CharField()
    description = TextField(null=True)

    status = CharField(default="unknown", index=True)
    status_source = CharField(default="calculated")
    status_message = TextField(null=True)
    status_updated_at = DateTimeField(null=True)

    manual_status = CharField(max_length=32, null=True, index=True)
    manual_status_message = TextField(null=True)
    manual_status_until = DateTimeField(null=True, index=True)
    manual_status_set_by = ForeignKeyField(User, null=True, backref="business_service_status_overrides", on_delete="SET NULL")
    manual_status_set_at = DateTimeField(null=True)

    criticality = CharField(default="important", index=True)
    tier = CharField(default="tier_2", index=True)

    public = BooleanField(default=True, index=True)
    public_name = CharField(null=True)
    public_description = TextField(null=True)
    public_order = IntegerField(default=100)

    labels = JSONTextField(default=dict)
    metadata = JSONTextField(default=dict)

    enabled = BooleanField(default=True, index=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "business_service"
        indexes = (
            (("group", "slug"), True),
            (("group", "enabled"), False),
            (("group", "public"), False),
            (("status", "enabled"), False),
            (("criticality", "enabled"), False),
        )


class BusinessServiceComponent(SoftDeleteModel):
    """Technical service component of a business service."""

    id = AutoField()
    business_service = ForeignKeyField(BusinessService, backref="components", on_delete="CASCADE")
    service = ForeignKeyField(Service, backref="business_components", on_delete="CASCADE")

    component_type = CharField(default="technical_service", index=True)
    criticality = CharField(default="required", index=True)
    impact_weight = IntegerField(default=100)
    position = IntegerField(default=0)

    status_rule = CharField(default="inherit")
    description = TextField(null=True)

    enabled = BooleanField(default=True, index=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "business_service_component"
        indexes = (
            (("business_service", "service"), True),
            (("business_service", "enabled"), False),
            (("service", "enabled"), False),
            (("criticality", "enabled"), False),
        )


class BusinessServiceStatusHistory(BaseModel):
    """Historical calculated or manual status changes for a business service."""

    id = AutoField()
    business_service = ForeignKeyField(BusinessService, backref="status_history", on_delete="CASCADE")
    old_status = CharField(null=True)
    new_status = CharField(index=True)
    status_source = CharField(default="calculated", index=True)
    message = TextField(null=True)
    impact_score = IntegerField(default=0)
    component_snapshot = JSONTextField(default=list)
    created_at = DateTimeField(default=datetime.utcnow, index=True)

    class Meta:
        table_name = "business_service_status_history"
        indexes = (
            (("business_service", "created_at"), False),
            (("business_service", "new_status"), False),
        )


class BusinessServiceIncidentImpact(BaseModel):
    """Persisted business impact snapshot for an alert group."""

    id = AutoField()
    business_service = ForeignKeyField(BusinessService, backref="incident_impacts", on_delete="CASCADE")
    group = DeferredForeignKey("AlertGroup", backref="business_impacts", on_delete="CASCADE")
    service = ForeignKeyField(Service, null=True, backref="business_incident_impacts", on_delete="SET NULL")

    impact_status = CharField(index=True)
    impact_score = IntegerField(default=0, index=True)
    relation = CharField(default="component_alert", index=True)
    reason = TextField(null=True)
    active = BooleanField(default=True, index=True)

    component_snapshot = JSONTextField(default=list)

    first_seen_at = DateTimeField(default=datetime.utcnow, index=True)
    last_seen_at = DateTimeField(default=datetime.utcnow, index=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "business_service_incident_impact"
        indexes = (
            (("business_service", "group", "relation"), True),
            (("business_service", "active"), False),
            (("group", "active"), False),
            (("impact_status", "active"), False),
        )


class AlertGroupCorrelation(BaseModel):
    """Persisted dependency-aware correlation between alert groups."""

    id = AutoField()

    root_group = DeferredForeignKey(
        "AlertGroup",
        backref="root_correlations",
        on_delete="CASCADE",
    )

    related_group = DeferredForeignKey(
        "AlertGroup",
        backref="related_correlations",
        on_delete="CASCADE",
    )

    team = ForeignKeyField(
        Team,
        null=True,
        backref="alert_group_correlations",
        on_delete="SET NULL",
    )

    root_service = ForeignKeyField(
        Service,
        null=True,
        backref="root_alert_correlations",
        on_delete="SET NULL",
    )

    related_service = ForeignKeyField(
        Service,
        null=True,
        backref="related_alert_correlations",
        on_delete="SET NULL",
    )

    dependency = ForeignKeyField(
        ServiceDependency,
        null=True,
        backref="alert_group_correlations",
        on_delete="SET NULL",
    )

    relation_type = CharField(max_length=64, index=True)
    direction = CharField(max_length=32, index=True)

    score = IntegerField(default=0, index=True)
    depth = IntegerField(default=1)

    dependency_type = CharField(max_length=32, null=True)
    criticality = CharField(max_length=32, null=True)

    reason = TextField(null=True)
    active = BooleanField(default=True, index=True)

    first_seen_at = DateTimeField(default=datetime.utcnow, index=True)
    last_seen_at = DateTimeField(default=datetime.utcnow, index=True)
    updated_at = DateTimeField(default=datetime.utcnow)
    created_at = DateTimeField(default=datetime.utcnow)

    context = JSONTextField(default=dict)

    class Meta:
        table_name = "alert_group_correlation"
        indexes = (
            (("root_group", "related_group", "relation_type"), True),
            (("root_group", "active"), False),
            (("related_group", "active"), False),
            (("team", "active"), False),
            (("relation_type", "active"), False),
            (("last_seen_at", "active"), False),
        )


class ServiceEvent(BaseModel):
    """Immutable event displayed in a service timeline."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)
    service = ForeignKeyField(Service, backref="events", on_delete="CASCADE")
    group = ForeignKeyField(Group, null=True, backref="service_events", on_delete="SET NULL")
    team = ForeignKeyField(Team, null=True, backref="service_events", on_delete="SET NULL")
    category = CharField(max_length=64, index=True)
    event_type = CharField(max_length=128, index=True)
    title = CharField()
    summary = TextField(null=True)
    source = CharField(max_length=64, default="incidentrelay", index=True)
    source_ref = CharField(max_length=191, null=True)
    dedup_key = CharField(max_length=191, null=True)
    external_url = TextField(null=True)
    actor_type = CharField(max_length=32, default="system")
    actor_user = ForeignKeyField(User, null=True, backref="service_events", on_delete="SET NULL")
    actor_label = CharField(null=True)
    severity = CharField(max_length=32, null=True)
    status = CharField(max_length=32, null=True)
    occurred_at = DateTimeField(default=datetime.utcnow, index=True)
    recorded_at = DateTimeField(default=datetime.utcnow)
    schema_version = IntegerField(default=1)
    payload = JSONTextField(default=dict)

    class Meta:
        table_name = "service_event"
        indexes = (
            (("service", "occurred_at"), False),
            (("group", "occurred_at"), False),
            (("team", "occurred_at"), False),
            (("service", "category", "occurred_at"), False),
            (("service", "event_type", "occurred_at"), False),
            (("source", "source_ref"), False),
            (("service", "source", "dedup_key"), True),
        )


class ServiceImpactSnapshot(BaseModel):
    """Point-in-time Service Impact v2 computation snapshot."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)

    group = ForeignKeyField(Group, null=True, backref="service_impact_snapshots", on_delete="SET NULL")
    team = ForeignKeyField(Team, null=True, backref="service_impact_snapshots", on_delete="SET NULL")
    service = ForeignKeyField(Service, null=True, backref="impact_snapshots", on_delete="SET NULL")

    source = CharField(default="manual", index=True)
    scope = CharField(default="all", index=True)
    captured_at = DateTimeField(default=datetime.utcnow, index=True)

    max_depth = IntegerField(default=5)
    include_disabled = BooleanField(default=False)
    include_operational = BooleanField(default=True)

    services_count = IntegerField(default=0)
    affected_services = IntegerField(default=0)
    critical_services = IntegerField(default=0)
    major_outage_services = IntegerField(default=0)
    partial_outage_services = IntegerField(default=0)
    degraded_services = IntegerField(default=0)
    maintenance_services = IntegerField(default=0)
    unknown_services = IntegerField(default=0)

    alert_group_impacted_services = IntegerField(default=0)
    dependency_impacted_services = IntegerField(default=0)
    own_status_impacted_services = IntegerField(default=0)

    open_alert_groups_total = IntegerField(default=0)
    critical_open_alert_groups_total = IntegerField(default=0)
    upstream_issues_total = IntegerField(default=0)
    cycle_detected_count = IntegerField(default=0)
    depth_limited_count = IntegerField(default=0)

    summary = JSONTextField(default=dict)
    filters = JSONTextField(default=dict)
    payload = JSONTextField(default=dict)

    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_impact_snapshot"
        indexes = (
            (("captured_at",), False),
            (("team", "captured_at"), False),
            (("service", "captured_at"), False),
            (("source", "captured_at"), False),
        )


class ServiceImpactSnapshotItem(BaseModel):
    """One service row inside a Service Impact snapshot."""

    id = AutoField()
    snapshot = ForeignKeyField(ServiceImpactSnapshot, backref="items", on_delete="CASCADE")

    group = ForeignKeyField(Group, null=True, backref="service_impact_snapshot_items", on_delete="SET NULL")
    team = ForeignKeyField(Team, null=True, backref="service_impact_snapshot_items", on_delete="SET NULL")
    service = ForeignKeyField(Service, null=True, backref="impact_snapshot_items", on_delete="SET NULL")

    captured_at = DateTimeField(index=True)

    service_slug = CharField(null=True)
    service_name = CharField(null=True)
    team_slug = CharField(null=True)
    team_name = CharField(null=True)
    criticality = CharField(null=True)
    tier = CharField(null=True)

    own_status = CharField(default="operational", index=True)
    alert_impact_status = CharField(default="operational", index=True)
    dependency_impact_status = CharField(default="operational", index=True)
    effective_status = CharField(default="operational", index=True)
    primary_reason = CharField(default="none", index=True)

    open_alert_groups = IntegerField(default=0)
    critical_open_alert_groups = IntegerField(default=0)
    upstream_issues_count = IntegerField(default=0)

    blast_radius_direct = IntegerField(default=0)
    blast_radius_total = IntegerField(default=0)
    blast_radius_critical = IntegerField(default=0)
    blast_radius_tier_1 = IntegerField(default=0)

    cycle_detected = BooleanField(default=False, index=True)
    depth_limited = BooleanField(default=False, index=True)

    root_causes = JSONTextField(default=list)
    explanation = JSONTextField(null=True)
    blast_radius = JSONTextField(null=True)
    payload = JSONTextField(default=dict)

    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_impact_snapshot_item"
        indexes = (
            (("snapshot", "service"), True),
            (("captured_at", "effective_status"), False),
            (("team", "captured_at"), False),
            (("service", "captured_at"), False),
            (("primary_reason", "captured_at"), False),
        )


class ServiceStandard(SoftDeleteModel):
    """Readiness standard applied to services within a group."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)
    group = ForeignKeyField(Group, backref="service_standards", on_delete="CASCADE")
    slug = CharField()
    name = CharField()
    description = TextField(null=True)
    applies_to = JSONTextField(default=dict)
    enabled = BooleanField(default=True)
    created_by = ForeignKeyField(User, null=True, backref="created_service_standards", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_standard"
        indexes = (
            (("group", "slug"), True),
            (("group", "enabled"), False),
        )


class ServiceStandardCheck(SoftDeleteModel):
    """One readiness check belonging to a service standard."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)
    standard = ForeignKeyField(ServiceStandard, backref="checks", on_delete="CASCADE")
    slug = CharField()
    name = CharField()
    description = TextField(null=True)
    check_type = CharField(index=True)
    configuration = JSONTextField(default=dict)
    weight = IntegerField(default=1)
    severity = CharField(default="warning")
    required = BooleanField(default=True)
    enabled = BooleanField(default=True)
    position = IntegerField(default=0)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_standard_check"
        indexes = (
            (("standard", "slug"), True),
            (("standard", "position"), False),
            (("check_type", "enabled"), False),
        )


class ServiceReadinessEvaluation(BaseModel):
    """Immutable evaluation of one standard against one service."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)
    batch_uid = UUIDField(index=True)
    service = ForeignKeyField(Service, backref="readiness_evaluations", on_delete="CASCADE")
    standard = ForeignKeyField(ServiceStandard, backref="evaluations", on_delete="CASCADE")
    status = CharField(index=True)
    score = IntegerField(default=0)
    passed_weight = IntegerField(default=0)
    total_weight = IntegerField(default=0)
    checks_count = IntegerField(default=0)
    failed_count = IntegerField(default=0)
    failed_required_count = IntegerField(default=0)
    failed_critical_count = IntegerField(default=0)
    trigger = CharField(default="system")
    actor_user = ForeignKeyField(User, null=True, backref="service_readiness_evaluations", on_delete="SET NULL")
    content_hash = CharField(null=True, index=True)
    evaluated_at = DateTimeField(default=datetime.utcnow, index=True)

    class Meta:
        table_name = "service_readiness_evaluation"
        indexes = (
            (("service", "evaluated_at"), False),
            (("standard", "evaluated_at"), False),
            (("service", "standard", "evaluated_at"), False),
            (("batch_uid", "service"), False),
        )


class ServiceReadinessCheckResult(BaseModel):
    """Immutable result of one readiness check."""

    id = AutoField()
    evaluation = ForeignKeyField(ServiceReadinessEvaluation, backref="results", on_delete="CASCADE")
    check = ForeignKeyField(ServiceStandardCheck, null=True, backref="evaluation_results", on_delete="SET NULL")
    check_uid = UUIDField(null=True)
    check_slug = CharField()
    check_name = CharField()
    check_type = CharField()
    status = CharField(index=True)
    weight = IntegerField(default=1)
    severity = CharField(default="warning")
    required = BooleanField(default=True)
    message = TextField(null=True)
    details = JSONTextField(default=dict)
    evaluated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_readiness_check_result"
        indexes = (
            (("evaluation", "status"), False),
            (("check_slug", "status"), False),
        )


class ServiceReadinessState(BaseModel):
    """Current aggregated readiness state for a service."""

    id = AutoField()
    service = ForeignKeyField(Service, unique=True, backref="readiness_state", on_delete="CASCADE")
    batch_uid = UUIDField(index=True)
    status = CharField(index=True)
    score = IntegerField(default=0, index=True)
    standards_count = IntegerField(default=0)
    checks_count = IntegerField(default=0)
    failed_count = IntegerField(default=0)
    failed_required_count = IntegerField(default=0)
    failed_critical_count = IntegerField(default=0)
    content_hash = CharField(null=True, index=True)
    evaluated_at = DateTimeField(default=datetime.utcnow, index=True)

    class Meta:
        table_name = "service_readiness_state"
        indexes = (
            (("status", "score"), False),
            (("evaluated_at", "status"), False),
        )


class ServiceRunbook(SoftDeleteModel):
    """Runbook attached to a service."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="runbooks", on_delete="CASCADE")

    title = CharField()
    description = TextField(null=True)
    url = TextField()

    severity = CharField(null=True)
    matcher_preset = ForeignKeyField(
        MatcherPreset,
        null=True,
        backref="service_runbooks",
        on_delete="RESTRICT",
    )
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


class ServiceSli(SoftDeleteModel):
    """Service Level Indicator definition for a service."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="slis", on_delete="CASCADE")

    slug = CharField()
    name = CharField()
    description = TextField(null=True)

    sli_type = CharField(index=True)
    source = CharField(default="incidentrelay_alert_groups", index=True)
    configuration = JSONTextField(default=dict)

    severity = CharField(null=True, index=True)
    priority = CharField(null=True, index=True)

    enabled = BooleanField(default=True, index=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_sli"
        indexes = (
            (("service", "slug"), True),
            (("service", "enabled"), False),
            (("sli_type", "source"), False),
        )


class ServiceSlo(SoftDeleteModel):
    """Service Level Objective attached to one SLI."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="slos", on_delete="CASCADE")
    sli = ForeignKeyField(ServiceSli, backref="slos", on_delete="CASCADE")

    name = CharField()
    description = TextField(null=True)

    comparison = CharField(default="percent_good_gte")
    target_percent_basis_points = IntegerField(null=True)
    threshold_seconds = IntegerField(null=True)
    threshold_count = IntegerField(null=True)
    window_days = IntegerField(default=30)

    exclude_maintenance = BooleanField(default=True)
    include_open_alerts = BooleanField(default=True)

    enabled = BooleanField(default=True, index=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "service_slo"
        indexes = (
            (("service", "name"), True),
            (("service", "enabled"), False),
            (("sli", "enabled"), False),
        )


class ServiceSloMeasurement(BaseModel):
    """Point-in-time SLO calculation result."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="slo_measurements", on_delete="CASCADE")
    sli = ForeignKeyField(ServiceSli, backref="measurements", on_delete="CASCADE")
    slo = ForeignKeyField(ServiceSlo, backref="measurements", on_delete="CASCADE")

    window_start = DateTimeField(index=True)
    window_end = DateTimeField(index=True)
    status = CharField(index=True)

    value_basis_points = IntegerField(null=True)
    value_count = IntegerField(null=True)
    target_basis_points = IntegerField(null=True)
    threshold_seconds = IntegerField(null=True)
    threshold_count = IntegerField(null=True)

    good_count = IntegerField(default=0)
    total_count = IntegerField(default=0)
    bad_count = IntegerField(default=0)
    pending_count = IntegerField(default=0)

    downtime_seconds = IntegerField(null=True)
    budget_seconds = IntegerField(null=True)
    budget_consumed_seconds = IntegerField(null=True)
    budget_remaining_seconds = IntegerField(null=True)

    calculated_at = DateTimeField(default=datetime.utcnow, index=True)
    details = JSONTextField(default=dict)

    class Meta:
        table_name = "service_slo_measurement"
        indexes = (
            (("slo", "calculated_at"), False),
            (("service", "calculated_at"), False),
            (("status", "calculated_at"), False),
        )


class Heartbeat(SoftDeleteModel):
    """Dead-man-switch check expecting recurring success pings."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)

    group = ForeignKeyField(Group, null=True, backref="heartbeats", on_delete="CASCADE")
    team = ForeignKeyField(Team, backref="heartbeats", on_delete="CASCADE")
    service = ForeignKeyField(Service, null=True, backref="heartbeats", on_delete="SET NULL")
    route = DeferredForeignKey("AlertRoute", backref="heartbeats", on_delete="CASCADE")

    name = CharField()
    slug = CharField()
    description = TextField(null=True)

    mode = CharField(default="interval", index=True)
    expected_interval_seconds = IntegerField(null=True)
    grace_period_seconds = IntegerField(default=300)

    schedule_kind = CharField(null=True)
    schedule_time = CharField(null=True)
    schedule_weekday = IntegerField(null=True)
    schedule_monthday = IntegerField(null=True)
    timezone = CharField(default="UTC")

    status = CharField(default="new", index=True)
    enabled = BooleanField(default=True, index=True)
    auto_resolve = BooleanField(default=True)

    instance_tracking_enabled = BooleanField(default=False, index=True)
    instance_key = CharField(default="instance")
    expected_instances_mode = CharField(default="none", index=True)
    auto_discovery_ttl_days = IntegerField(null=True)

    severity = CharField(default="critical", index=True)
    priority_slug = CharField(default="p2", index=True)

    token_prefix = CharField(null=True, index=True)
    token_hash = CharField(unique=True, index=True)

    last_seen_at = DateTimeField(null=True, index=True)
    last_payload = JSONTextField(null=True)
    last_remote_addr = CharField(null=True)
    last_user_agent = TextField(null=True)

    next_expected_at = DateTimeField(null=True, index=True)
    overdue_since = DateTimeField(null=True, index=True)
    last_overdue_at = DateTimeField(null=True)
    last_recovered_at = DateTimeField(null=True)

    current_alert_group = DeferredForeignKey(
        "AlertGroup",
        null=True,
        backref="heartbeat_overdue_checks",
        on_delete="SET NULL",
    )

    labels = JSONTextField(default=dict)
    metadata = JSONTextField(default=dict)

    created_by = ForeignKeyField(User, null=True, backref="created_heartbeats", on_delete="SET NULL")
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "heartbeat"
        indexes = (
            (("team", "slug"), True),
            (("team", "status"), False),
            (("group", "enabled"), False),
            (("route", "enabled"), False),
            (("status", "next_expected_at"), False),
            (("team", "instance_tracking_enabled"), False),
        )


class HeartbeatInstance(BaseModel):
    """Per-producer state for multi-instance heartbeats."""

    id = AutoField()
    heartbeat = ForeignKeyField(Heartbeat, backref="instances", on_delete="CASCADE")
    instance_key = CharField()

    status = CharField(default="new", index=True)
    enabled = BooleanField(default=True, index=True)
    auto_discovered = BooleanField(default=True, index=True)

    first_seen_at = DateTimeField(null=True)
    last_seen_at = DateTimeField(null=True, index=True)
    last_payload = JSONTextField(null=True)
    last_remote_addr = CharField(null=True)
    last_user_agent = TextField(null=True)

    next_expected_at = DateTimeField(null=True, index=True)
    overdue_since = DateTimeField(null=True, index=True)
    last_overdue_at = DateTimeField(null=True)
    last_recovered_at = DateTimeField(null=True)

    current_alert_group = DeferredForeignKey(
        "AlertGroup",
        null=True,
        backref="heartbeat_instance_overdue_checks",
        on_delete="SET NULL",
    )

    metadata = JSONTextField(default=dict)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "heartbeat_instance"
        indexes = (
            (("heartbeat", "instance_key"), True),
            (("heartbeat", "status"), False),
            (("enabled", "next_expected_at"), False),
            (("heartbeat", "auto_discovered"), False),
        )


class HeartbeatPing(BaseModel):
    """History of heartbeat pings and state transitions."""

    id = AutoField()
    heartbeat = ForeignKeyField(Heartbeat, backref="pings", on_delete="CASCADE")
    received_at = DateTimeField(default=datetime.utcnow, index=True)
    event_type = CharField(default="ping", index=True)
    instance_key = CharField(null=True, index=True)
    status_before = CharField(null=True)
    status_after = CharField(null=True)
    message = TextField(null=True)
    payload = JSONTextField(null=True)
    remote_addr = CharField(null=True)
    user_agent = TextField(null=True)
    alert_group = DeferredForeignKey("AlertGroup", null=True, backref="heartbeat_events", on_delete="SET NULL")

    class Meta:
        table_name = "heartbeat_ping"
        indexes = (
            (("heartbeat", "received_at"), False),
            (("heartbeat", "event_type"), False),
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


class OnCallShiftMattermostNotification(BaseModel):
    """Deduplication log for personal Mattermost on-call shift notifications."""

    id = AutoField()

    user = ForeignKeyField(User, backref="oncall_shift_mattermost_notifications", on_delete="CASCADE")
    rotation = ForeignKeyField(Rotation, backref="oncall_shift_mattermost_notifications", on_delete="CASCADE")

    event_type = CharField(index=True)  # shift_start

    slot_start_at = DateTimeField(index=True)
    slot_end_at = DateTimeField(index=True)

    layer_id = IntegerField(null=True)
    override_id = IntegerField(null=True)

    mattermost_user_id = CharField(index=True)
    fingerprint = CharField(unique=True, index=True)

    status = CharField(default="pending", index=True)  # pending | sent | failed | skipped
    last_error = TextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    sent_at = DateTimeField(null=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "oncall_shift_mattermost_notification"
        indexes = (
            (("user", "event_type", "slot_start_at", "slot_end_at"), False),
            (("rotation", "event_type", "slot_start_at"), False),
            (("mattermost_user_id", "event_type", "slot_start_at"), False),
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
    """Map external SSO group value to IncidentRelay group and optional team role."""

    id = AutoField()
    provider = ForeignKeyField(SsoProvider, backref="group_mappings", on_delete="CASCADE")

    external_group = CharField()
    incidentrelay_group = ForeignKeyField(
        Group,
        backref="sso_group_mappings",
        on_delete="CASCADE",
    )

    group_role = CharField(default="viewer")
    incidentrelay_team = ForeignKeyField(
        Team,
        null=True,
        backref="sso_group_mappings",
        on_delete="CASCADE",
    )
    team_role = CharField(null=True)
    active = BooleanField(default=True)
    priority = IntegerField(default=100)

    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "sso_group_mapping"
        indexes = (
            (("provider", "external_group", "incidentrelay_group", "incidentrelay_team"), True),
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

# BEGIN EVENT ORCHESTRATION V1 MODELS

EVENT_ORCHESTRATION_SCOPES = ("global", "service")
EVENT_ORCHESTRATION_MODES = ("active", "shadow", "disabled")
EVENT_ORCHESTRATION_VERSION_STATUSES = ("draft", "published", "archived")
EVENT_ORCHESTRATION_PROCESSING_MODES = (
    "continue",
    "stop",
    "evaluate_children",
    "children_then_continue",
)


class EventOrchestration(SoftDeleteModel):
    """A group-owned orchestration with one atomically selected active version."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)
    group = ForeignKeyField(
        Group,
        backref="event_orchestrations",
        on_delete="CASCADE",
        index=True,
    )
    name = CharField(max_length=255)
    description = TextField(null=True)
    scope = CharField(max_length=32, default="global", index=True)
    service = ForeignKeyField(
        Service,
        backref="event_orchestrations",
        null=True,
        on_delete="SET NULL",
        index=True,
    )
    enabled = BooleanField(default=False, index=True)
    mode = CharField(max_length=32, default="disabled", index=True)
    # Kept as an integer to avoid a circular DDL dependency between the
    # orchestration and orchestration-version tables. Repository code verifies
    # that the selected version belongs to this orchestration.
    active_version_id = IntegerField(null=True, index=True)
    created_by = ForeignKeyField(
        User,
        backref="created_event_orchestrations",
        null=True,
        on_delete="SET NULL",
    )
    created_at = DateTimeField(default=datetime.utcnow, index=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "event_orchestration"
        indexes = (
            (("group", "name"), True),
            (("group", "scope"), False),
            (("group", "mode", "enabled"), False),
            (("service", "enabled"), False),
        )

    def save(self, *args, **kwargs):
        if self.scope not in EVENT_ORCHESTRATION_SCOPES:
            raise ValueError("Invalid orchestration scope")
        if self.mode not in EVENT_ORCHESTRATION_MODES:
            raise ValueError("Invalid orchestration mode")

        if self.scope == "global" and self.service_id is not None:
            raise ValueError("Global orchestration cannot reference a service")
        if self.scope == "service" and self.service_id is None:
            raise ValueError("Service-scoped orchestration requires a service")

        if self.service_id is not None:
            service_group_id = (
                Service.select(Service.group)
                .where(Service.id == self.service_id)
                .scalar()
            )
            if service_group_id is None:
                raise ValueError("Referenced service does not exist")
            if int(service_group_id) != int(self.group_id):
                raise ValueError("Referenced service belongs to another group")

        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


class EventOrchestrationVersion(BaseModel):
    """An immutable published orchestration definition."""

    id = AutoField()
    orchestration = ForeignKeyField(
        EventOrchestration,
        backref="versions",
        on_delete="CASCADE",
        index=True,
    )
    version_number = IntegerField()
    status = CharField(max_length=32, default="draft", index=True)
    definition_hash = CharField(max_length=64, null=True, index=True)
    definition_json = JSONTextField(default=dict)
    comment = TextField(null=True)
    created_by = ForeignKeyField(
        User,
        backref="created_event_orchestration_versions",
        null=True,
        on_delete="SET NULL",
    )
    published_by = ForeignKeyField(
        User,
        backref="published_event_orchestration_versions",
        null=True,
        on_delete="SET NULL",
    )
    created_at = DateTimeField(default=datetime.utcnow, index=True)
    updated_at = DateTimeField(default=datetime.utcnow)
    published_at = DateTimeField(null=True, index=True)

    class Meta:
        table_name = "event_orchestration_version"
        indexes = (
            (("orchestration", "version_number"), True),
            (("orchestration", "status"), False),
        )

    def save(self, *args, **kwargs):
        if self.status not in EVENT_ORCHESTRATION_VERSION_STATUSES:
            raise ValueError("Invalid orchestration version status")

        if self.id is None and self.status != "draft":
            raise ValueError("New orchestration versions must start as drafts")

        if self.id is not None:
            current = (
                EventOrchestrationVersion.select(
                    EventOrchestrationVersion.status,
                )
                .where(EventOrchestrationVersion.id == self.id)
                .dicts()
                .get()
            )
            dirty = {field.name for field in self.dirty_fields}
            current_status = current["status"]

            # A published version may only be archived. All other changes are
            # rejected. Repository publication uses an atomic UPDATE for this
            # narrowly allowed state transition.
            archive_only = (
                current_status == "published"
                and self.status == "archived"
                and dirty.issubset({"status", "updated_at"})
            )
            if current_status in ("published", "archived") and not archive_only:
                raise ValueError("Published orchestration versions are immutable")

        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)

    def delete_instance(self, *args, **kwargs):
        if self.status != "draft":
            raise ValueError("Published orchestration versions cannot be deleted")
        return super().delete_instance(*args, **kwargs)


class EventOrchestrationRule(BaseModel):
    """A deterministic ordered rule tree belonging to one draft/version."""

    id = AutoField()
    version = ForeignKeyField(
        EventOrchestrationVersion,
        backref="rules",
        on_delete="CASCADE",
        index=True,
    )
    parent_rule = ForeignKeyField(
        "self",
        backref="children",
        null=True,
        on_delete="CASCADE",
        index=True,
    )
    position = IntegerField(default=0)
    name = CharField(max_length=255)
    description = TextField(null=True)
    enabled = BooleanField(default=True, index=True)
    condition_tree_json = JSONTextField(default=dict)
    actions_json = JSONTextField(default=list)
    processing_mode = CharField(max_length=32, default="continue")
    created_at = DateTimeField(default=datetime.utcnow, index=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "event_orchestration_rule"
        indexes = (
            (("version", "parent_rule", "position"), True),
            (("version", "enabled"), False),
        )

    def _assert_draft(self):
        version_status = (
            EventOrchestrationVersion.select(EventOrchestrationVersion.status)
            .where(EventOrchestrationVersion.id == self.version_id)
            .scalar()
        )
        if version_status != "draft":
            raise ValueError("Rules of published orchestration versions are immutable")

    def save(self, *args, **kwargs):
        if self.processing_mode not in EVENT_ORCHESTRATION_PROCESSING_MODES:
            raise ValueError("Invalid orchestration rule processing mode")
        if self.version_id is None:
            raise ValueError("Orchestration rule requires a version")
        self._assert_draft()

        if self.parent_rule_id is not None:
            parent_version_id = (
                EventOrchestrationRule.select(EventOrchestrationRule.version)
                .where(EventOrchestrationRule.id == self.parent_rule_id)
                .scalar()
            )
            if parent_version_id is None:
                raise ValueError("Parent orchestration rule does not exist")
            if int(parent_version_id) != int(self.version_id):
                raise ValueError("Parent rule belongs to another version")

        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)

    def delete_instance(self, *args, **kwargs):
        self._assert_draft()
        return super().delete_instance(*args, **kwargs)


class OrchestrationIntakeToken(BaseModel):
    """Hashed intake credential scoped to a single orchestration."""

    id = AutoField()
    orchestration = ForeignKeyField(
        EventOrchestration,
        backref="intake_tokens",
        on_delete="CASCADE",
        index=True,
    )
    name = CharField(max_length=255)
    token_hash = CharField(max_length=255, unique=True, index=True)
    token_prefix = CharField(max_length=24, null=True, index=True)
    enabled = BooleanField(default=True, index=True)
    created_by = ForeignKeyField(
        User,
        backref="created_orchestration_intake_tokens",
        null=True,
        on_delete="SET NULL",
    )
    created_at = DateTimeField(default=datetime.utcnow, index=True)
    last_used_at = DateTimeField(null=True)
    revoked_at = DateTimeField(null=True, index=True)

    class Meta:
        table_name = "orchestration_intake_token"
        indexes = (
            (("orchestration", "name"), True),
            (("orchestration", "enabled"), False),
        )


class OrchestrationExecution(BaseModel):
    """Immutable execution audit record for explainability and retention."""

    id = AutoField()
    uid = UUIDField(default=uuid.uuid4, unique=True, index=True)
    group = ForeignKeyField(
        Group,
        backref="orchestration_executions",
        on_delete="CASCADE",
        index=True,
    )
    orchestration = ForeignKeyField(
        EventOrchestration,
        backref="executions",
        on_delete="CASCADE",
        index=True,
    )
    version = ForeignKeyField(
        EventOrchestrationVersion,
        backref="executions",
        on_delete="RESTRICT",
        index=True,
    )
    source = CharField(max_length=128, null=True, index=True)
    integration_name = CharField(max_length=255, null=True)
    event_fingerprint = CharField(max_length=255, null=True, index=True)
    disposition = CharField(max_length=64, null=True, index=True)
    matched_rule_count = IntegerField(default=0)
    duration_ms = IntegerField(null=True)
    trace_json = JSONTextField(default=dict)
    # Deliberately retained as scalar IDs: execution history must remain
    # readable even if an alert or alert group is later removed.
    alert_id = IntegerField(null=True, index=True)
    alert_group_id = IntegerField(null=True, index=True)
    created_at = DateTimeField(default=datetime.utcnow, index=True)
    expires_at = DateTimeField(null=True, index=True)

    class Meta:
        table_name = "orchestration_execution"
        indexes = (
            (("group", "created_at"), False),
            (("orchestration", "created_at"), False),
            (("version", "created_at"), False),
            (("event_fingerprint", "created_at"), False),
        )


# END EVENT ORCHESTRATION V1 MODELS
