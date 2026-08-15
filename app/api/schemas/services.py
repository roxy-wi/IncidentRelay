from typing import Any, Dict, List, Literal

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from app.api.schemas.base import ApiModel
from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    SLUG_MAX_LENGTH,
    SLUG_MIN_LENGTH,
)


SERVICE_TYPE_PATTERN = (
    r"^(api|web|database|queue|cache|worker|cron|network|storage|"
    r"infrastructure|external|other)$"
)

SERVICE_ENVIRONMENT_PATTERN = r"^(production|staging|development|testing|shared)$"

SERVICE_CRITICALITY_PATTERN = r"^(low|medium|high|critical)$"

SERVICE_TIER_PATTERN = r"^(tier_1|tier_2|tier_3|tier_4)$"

SERVICE_STATUS_PATTERN = (
    r"^(operational|degraded|partial_outage|major_outage|"
    r"maintenance|disabled|unknown)$"
)

SERVICE_STATUS_SOURCE_PATTERN = r"^(manual|alerts|maintenance|system)$"

SERVICE_LINK_TYPE_PATTERN = (
    r"^(dashboard|metrics|logs|traces|repository|documentation|"
    r"status_page|wiki|other)$"
)

SERVICE_DEPENDENCY_TYPE_PATTERN = r"^(hard|soft|external|informational)$"

SERVICE_DEPENDENCY_CRITICALITY_PATTERN = r"^(required|important|optional)$"

SERVICE_IMPACT_STATUS_PATTERN = (
    r"^(operational|degraded|partial_outage|major_outage|"
    r"maintenance|disabled|unknown)$"
)

SERVICE_IMPACT_REASON_PATTERN = (
    r"^(none|own_status|alert_group|upstream_dependency|"
    r"maintenance|disabled|unknown)$"
)

SERVICE_IMPACT_SORT_PATTERN = (
    r"^(service|status|effective_status|blast_radius|criticality|tier)$"
)

SERVICE_IMPACT_ORDER_PATTERN = r"^(asc|desc)$"

SERVICE_IMPACT_MAX_DEPTH_DEFAULT = 5
SERVICE_IMPACT_MAX_DEPTH_LIMIT = 10
SERVICE_IMPACT_LIMIT_DEFAULT = 100
SERVICE_IMPACT_LIMIT_MAX = 500

SERVICE_OWNER_ROLE_PATTERN = (
    r"^(owner|stakeholder|business_owner|executive|support|"
    r"customer_success|custom)$"
)


class ServiceOwnerBaseSchema(ApiModel):
    """Validate service owner input."""

    user_id: int = Field(ge=1)
    role: str = Field(default="owner", pattern=SERVICE_OWNER_ROLE_PATTERN)
    active: bool = True
    notify_on_created: bool = True
    notify_on_priority_change: bool = True
    notify_on_status_change: bool = True
    notify_on_resolved: bool = True
    notify_on_comment: bool = True


class ServiceOwnerCreateSchema(ServiceOwnerBaseSchema):
    """Validate service owner creation."""


class ServiceOwnerUpdateSchema(ServiceOwnerBaseSchema):
    """Validate service owner update."""


SERVICE_STANDARD_CHECK_TYPE_PATTERN = (
    r"^(field_present|field_equals|owner_exists|active_rotation_exists|"
    r"escalation_policy_exists|notification_policy_exists|"
    r"service_channel_exists|route_exists|match_rule_exists|runbook_exists|"
    r"link_type_exists|dependency_exists|dependency_cycle_absent|metadata_value)$"
)

SERVICE_STANDARD_CHECK_SEVERITY_PATTERN = r"^(info|warning|critical)$"


class ServiceStandardBaseSchema(ApiModel):
    """Validate service standard input."""

    slug: str = Field(
        min_length=SLUG_MIN_LENGTH,
        max_length=SLUG_MAX_LENGTH,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    name: str = Field(min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    applies_to: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ServiceStandardCreateSchema(ServiceStandardBaseSchema):
    """Validate service standard creation."""

    group_id: int = Field(ge=1)


class ServiceStandardUpdateSchema(ServiceStandardBaseSchema):
    """Validate service standard update."""


class ServiceStandardCheckBaseSchema(ApiModel):
    """Validate service standard check input."""

    slug: str = Field(
        min_length=SLUG_MIN_LENGTH,
        max_length=SLUG_MAX_LENGTH,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    name: str = Field(min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    check_type: str = Field(pattern=SERVICE_STANDARD_CHECK_TYPE_PATTERN)
    configuration: Dict[str, Any] = Field(default_factory=dict)
    weight: int = Field(default=1, ge=1, le=100)
    severity: str = Field(default="warning", pattern=SERVICE_STANDARD_CHECK_SEVERITY_PATTERN)
    required: bool = True
    enabled: bool = True
    position: int = Field(default=0, ge=0)


class ServiceStandardCheckCreateSchema(ServiceStandardCheckBaseSchema):
    """Validate service standard check creation."""


class ServiceStandardCheckUpdateSchema(ServiceStandardCheckBaseSchema):
    """Validate service standard check update."""


class ServiceStandardPresetApplySchema(ApiModel):
    """Validate service standard preset application."""

    group_id: int = Field(ge=1)


class ServiceBaseSchema(ApiModel):
    """Validate service input."""

    team_id: int = Field(ge=1)

    slug: str = Field(
        min_length=SLUG_MIN_LENGTH,
        max_length=SLUG_MAX_LENGTH,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    name: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    service_type: str = Field(default="other", pattern=SERVICE_TYPE_PATTERN)
    environment: str = Field(default="production", pattern=SERVICE_ENVIRONMENT_PATTERN)
    criticality: str = Field(default="medium", pattern=SERVICE_CRITICALITY_PATTERN)
    tier: str = Field(default="tier_3", pattern=SERVICE_TIER_PATTERN)

    status: str = Field(default="operational", pattern=SERVICE_STATUS_PATTERN)
    status_source: str = Field(default="manual", pattern=SERVICE_STATUS_SOURCE_PATTERN)
    status_message: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )

    default_rotation_id: int | None = Field(default=None, ge=1)
    default_escalation_policy_id: int | None = Field(default=None, ge=1)
    notification_policy_id: int | None = Field(default=None, ge=1)
    priority_policy_id: int | None = Field(default=None, ge=1)

    labels: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True
    public: bool = False
    public_name: str | None = Field(
        default=None,
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )
    public_description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )
    public_order: int = Field(default=100, ge=0)
    kind: Literal["technical"] = "technical"
    lifecycle: Literal["experimental", "development", "production", "deprecated", "retired"] = "production"


class ServiceCreateSchema(ServiceBaseSchema):
    """Validate service creation."""


class ServiceUpdateSchema(ServiceBaseSchema):
    """Validate service update."""


class ServiceMatchRuleBaseSchema(ApiModel):
    """Validate service match rule input."""

    team_id: int = Field(ge=1)
    route_id: int | None = Field(default=None, ge=1)
    service_id: int = Field(ge=1)

    position: int = Field(default=0, ge=0)
    name: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )
    matcher_preset_id: int | None = Field(default=None, ge=1)
    matchers: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True

    @model_validator(mode="after")
    def validate_matchers(self):
        """Require a preset, local matchers or both."""
        if not self.matcher_preset_id and not self.matchers:
            raise ValueError("Service match rule must have a matcher preset or local matchers")
        return self


class ServiceMatchRuleCreateSchema(ServiceMatchRuleBaseSchema):
    """Validate service match rule creation."""


class ServiceMatchRuleUpdateSchema(ServiceMatchRuleBaseSchema):
    """Validate service match rule update."""


class ServiceLinkBaseSchema(ApiModel):
    """Validate service link input."""

    link_type: str = Field(default="other", pattern=SERVICE_LINK_TYPE_PATTERN)
    label: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )
    url: str = Field(min_length=3, max_length=2048)
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )
    priority: int = Field(default=100, ge=0)
    enabled: bool = True


class ServiceLinkCreateSchema(ServiceLinkBaseSchema):
    """Validate service link creation."""


class ServiceLinkUpdateSchema(ServiceLinkBaseSchema):
    """Validate service link update."""


class ServiceRunbookBaseSchema(ApiModel):
    """Validate service runbook input."""

    title: str = Field(min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    url: str = Field(min_length=3, max_length=2048)
    severity: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    matcher_preset_id: int | None = Field(default=None, ge=1)
    matchers: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0)
    enabled: bool = True


class ServiceRunbookCreateSchema(ServiceRunbookBaseSchema):
    """Validate service runbook creation."""


class ServiceRunbookUpdateSchema(ServiceRunbookBaseSchema):
    """Validate service runbook update."""


SERVICE_SLI_TYPE_PATTERN = (
    r"^(alert_ack_latency|alert_resolve_latency|incident_availability|incident_count)$"
)

SERVICE_SLI_SOURCE_PATTERN = r"^(incidentrelay_alert_groups|incidentrelay_service_status)$"

SERVICE_SLI_SEVERITY_PATTERN = r"^(critical|high|warning|info)$"

SERVICE_SLI_PRIORITY_PATTERN = r"^(p1|p2|p3|p4)$"
SERVICE_IMPACT_SLI_TYPES = {"incident_availability", "incident_count"}
SERVICE_SLI_PRIORITY_VALUES = ["p1", "p2", "p3", "p4"]
DEFAULT_IMPACT_PRIORITY_SCOPE = ["p1", "p2"]

SERVICE_SLO_COMPARISON_PATTERN = r"^(percent_good_gte|value_gte|value_lte)$"
SERVICE_SLO_NAME_MAX_LENGTH = 160


class ServiceSliBaseSchema(ApiModel):
    """Validate Service Level Indicator input."""

    slug: str = Field(
        min_length=SLUG_MIN_LENGTH,
        max_length=SLUG_MAX_LENGTH,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    name: str = Field(min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    sli_type: str = Field(pattern=SERVICE_SLI_TYPE_PATTERN)
    source: str = Field(default="incidentrelay_alert_groups", pattern=SERVICE_SLI_SOURCE_PATTERN)
    configuration: Dict[str, Any] = Field(default_factory=dict)
    severity: str | None = Field(default=None, pattern=SERVICE_SLI_SEVERITY_PATTERN)
    priority: str | None = Field(default=None, pattern=SERVICE_SLI_PRIORITY_PATTERN)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_scope_shape(self):
        """Validate and normalize SLI scope fields."""
        configuration = dict(self.configuration or {})
        priority_scope = configuration.get("priority_scope")

        if priority_scope is None and self.priority:
            priority_scope = [self.priority]

        if priority_scope is None and self.sli_type in SERVICE_IMPACT_SLI_TYPES:
            priority_scope = list(DEFAULT_IMPACT_PRIORITY_SCOPE)

        if isinstance(priority_scope, str):
            priority_scope = [priority_scope]

        normalized = []

        if priority_scope is not None:
            if not isinstance(priority_scope, list):
                raise PydanticCustomError(
                    "service_sli_priority_scope",
                    "priority_scope must be a list",
                )

            for value in priority_scope:
                value = str(value or "").strip().lower()

                if value not in SERVICE_SLI_PRIORITY_VALUES:
                    raise PydanticCustomError(
                        "service_sli_priority_scope",
                        "priority_scope values must be one of p1, p2, p3, p4",
                    )

                if value not in normalized:
                    normalized.append(value)

        if self.sli_type in SERVICE_IMPACT_SLI_TYPES and not normalized:
            raise PydanticCustomError(
                "service_sli_priority_scope",
                "Impact SLI requires priority_scope",
            )

        if normalized:
            configuration["priority_scope"] = normalized
            self.priority = normalized[0] if len(normalized) == 1 else None
        else:
            configuration.pop("priority_scope", None)
            self.priority = None

        if self.sli_type in SERVICE_IMPACT_SLI_TYPES:
            self.severity = None

        self.configuration = configuration

        return self


class ServiceSliCreateSchema(ServiceSliBaseSchema):
    """Validate Service Level Indicator creation."""


class ServiceSliUpdateSchema(ServiceSliBaseSchema):
    """Validate Service Level Indicator update."""


class ServiceSloBaseSchema(ApiModel):
    """Validate Service Level Objective input."""

    sli_id: int = Field(ge=1)
    name: str = Field(min_length=NAME_MIN_LENGTH, max_length=SERVICE_SLO_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    comparison: str | None = Field(default=None, pattern=SERVICE_SLO_COMPARISON_PATTERN)
    target_percent_basis_points: int | None = Field(default=None, ge=0, le=10000)
    threshold_seconds: int | None = Field(default=None, ge=1, le=90 * 24 * 3600)
    threshold_count: int | None = Field(default=None, ge=0, le=100000)
    window_days: int = Field(default=30, ge=1, le=365)
    exclude_maintenance: bool = True
    include_open_alerts: bool = True
    enabled: bool = True


class ServiceSloCreateSchema(ServiceSloBaseSchema):
    """Validate Service Level Objective creation."""


class ServiceSloUpdateSchema(ServiceSloBaseSchema):
    """Validate Service Level Objective update."""


class ServiceDependencyBaseSchema(ApiModel):
    """Validate service dependency input."""

    depends_on_service_id: int = Field(ge=1)
    dependency_type: str = Field(
        default="hard",
        pattern=SERVICE_DEPENDENCY_TYPE_PATTERN,
    )
    criticality: str = Field(
        default="important",
        pattern=SERVICE_DEPENDENCY_CRITICALITY_PATTERN,
    )
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )
    enabled: bool = True
    correlation_enabled: bool = True
    propagation_delay_seconds: int = Field(default=300, ge=0, le=86400)


class ServiceDependencyCreateSchema(ServiceDependencyBaseSchema):
    """Validate service dependency creation."""


class ServiceDependencyUpdateSchema(ServiceDependencyBaseSchema):
    """Validate service dependency update."""


class ServiceImpactQuerySchema(ApiModel):
    """Validate Service Impact v2 list query."""

    team_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)

    include_disabled: bool = False
    include_operational: bool = True

    include_explanation: bool = True
    include_root_causes: bool = True
    include_blast_radius: bool = True
    include_paths: bool = True

    max_depth: int = Field(
        default=SERVICE_IMPACT_MAX_DEPTH_DEFAULT,
        ge=1,
        le=SERVICE_IMPACT_MAX_DEPTH_LIMIT,
    )

    limit: int = Field(
        default=SERVICE_IMPACT_LIMIT_DEFAULT,
        ge=1,
        le=SERVICE_IMPACT_LIMIT_MAX,
    )

    sort: str = Field(default="effective_status", pattern=SERVICE_IMPACT_SORT_PATTERN)
    order: str = Field(default="desc", pattern=SERVICE_IMPACT_ORDER_PATTERN)


class ServiceImpactServiceQuerySchema(ApiModel):
    """Validate Service Impact v2 single-service query."""

    include_disabled: bool = False

    include_explanation: bool = True
    include_root_causes: bool = True
    include_blast_radius: bool = True
    include_paths: bool = True

    max_depth: int = Field(
        default=SERVICE_IMPACT_MAX_DEPTH_DEFAULT,
        ge=1,
        le=SERVICE_IMPACT_MAX_DEPTH_LIMIT,
    )


class ServiceImpactExplainQuerySchema(ApiModel):
    """Validate Service Impact v2 explanation query."""

    include_paths: bool = True
    include_root_causes: bool = True
    include_blast_radius: bool = True

    max_depth: int = Field(
        default=SERVICE_IMPACT_MAX_DEPTH_DEFAULT,
        ge=1,
        le=SERVICE_IMPACT_MAX_DEPTH_LIMIT,
    )


class ServiceImpactAnalyticsQuerySchema(ApiModel):
    """Validate Service Impact v2 analytics query."""

    team_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)

    days: int = Field(default=30, ge=1, le=365)
    include_disabled: bool = False
    include_operational: bool = False

    max_depth: int = Field(
        default=SERVICE_IMPACT_MAX_DEPTH_DEFAULT,
        ge=1,
        le=SERVICE_IMPACT_MAX_DEPTH_LIMIT,
    )


class ServiceImpactSnapshotQuerySchema(ApiModel):
    """Validate manual Service Impact snapshot creation query/body."""

    team_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)

    include_disabled: bool = False
    include_operational: bool = True
    include_explanation: bool = True
    include_root_causes: bool = True
    include_blast_radius: bool = True
    include_paths: bool = True

    max_depth: int = Field(
        default=SERVICE_IMPACT_MAX_DEPTH_DEFAULT,
        ge=1,
        le=SERVICE_IMPACT_MAX_DEPTH_LIMIT,
    )


class ServiceImpactSnapshotListQuerySchema(ApiModel):
    """Validate Service Impact snapshot list query."""

    team_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)
    days: int = Field(default=7, ge=1, le=365)
    limit: int = Field(default=50, ge=1, le=500)


class ServiceImpactHistoryQuerySchema(ApiModel):
    """Validate historical Service Impact analytics query."""

    team_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)
    days: int = Field(default=30, ge=1, le=365)
    bucket: str = Field(default="day", pattern=r"^(hour|day)$")
    limit: int = Field(default=25, ge=1, le=200)


class ServiceImpactPathNodeSchema(ApiModel):
    """Service node inside an impact path."""

    service_id: int = Field(ge=1)
    service_slug: str | None = None
    service_name: str | None = None
    status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    effective_status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    impact_score: int = Field(default=0, ge=0, le=100)
    propagated_impact_score: int | None = Field(default=None, ge=0, le=100)
    dependency_multiplier: float | None = None
    dependency_type: str | None = Field(default=None, pattern=SERVICE_DEPENDENCY_TYPE_PATTERN)
    dependency_criticality: str | None = Field(
        default=None,
        pattern=SERVICE_DEPENDENCY_CRITICALITY_PATTERN,
    )


class ServiceImpactRootCauseSchema(ApiModel):
    """Root cause entry for Service Impact v2."""

    service_id: int = Field(ge=1)
    service_slug: str | None = None
    service_name: str | None = None
    reason: str = Field(pattern=SERVICE_IMPACT_REASON_PATTERN)
    status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    effective_status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    impact_score: int = Field(default=0, ge=0, le=100)
    severity: str | None = None
    priority_slug: str | None = None
    priority_order: int | None = None
    open_alert_groups: int = Field(default=0, ge=0)
    critical_open_alert_groups: int = Field(default=0, ge=0)
    path: list[ServiceImpactPathNodeSchema] = Field(default_factory=list)


class ServiceImpactExplanationSchema(ApiModel):
    """Human-readable explanation block for Service Impact v2."""

    primary_reason: str = Field(pattern=SERVICE_IMPACT_REASON_PATTERN)
    primary_source_service_id: int | None = Field(default=None, ge=1)
    primary_source_service_slug: str | None = None
    primary_source_service_name: str | None = None

    title: str
    message: str

    own_impact_score: int = Field(default=0, ge=0, le=100)
    alert_impact_score: int = Field(default=0, ge=0, le=100)
    dependency_impact_score: int = Field(default=0, ge=0, le=100)
    effective_impact_score: int = Field(default=0, ge=0, le=100)

    rules: list[str] = Field(default_factory=list)
    paths: list[list[ServiceImpactPathNodeSchema]] = Field(default_factory=list)


class ServiceBlastRadiusSchema(ApiModel):
    """Downstream blast radius for a service."""

    direct_downstream: int = Field(default=0, ge=0)
    transitive_downstream: int = Field(default=0, ge=0)
    critical_downstream: int = Field(default=0, ge=0)
    tier_1_downstream: int = Field(default=0, ge=0)
    affected_downstream: int = Field(default=0, ge=0)
    paths: list[list[ServiceImpactPathNodeSchema]] = Field(default_factory=list)
    cycle_detected: bool = False
    depth_limited: bool = False


class ServiceImpactV2ItemSchema(ApiModel):
    """Single service item in Service Impact v2 response."""

    service_id: int = Field(ge=1)
    service_slug: str
    service_name: str

    team_id: int = Field(ge=1)
    team_slug: str | None = None
    team_name: str | None = None

    own_status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    alert_impact_status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    dependency_impact_status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    effective_status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)

    own_impact_score: int = Field(default=0, ge=0, le=100)
    alert_impact_score: int = Field(default=0, ge=0, le=100)
    dependency_impact_score: int = Field(default=0, ge=0, le=100)
    effective_impact_score: int = Field(default=0, ge=0, le=100)
    impact_score: int = Field(default=0, ge=0, le=100)

    primary_reason: str = Field(pattern=SERVICE_IMPACT_REASON_PATTERN)

    open_alert_groups: int = Field(default=0, ge=0)
    critical_open_alert_groups: int = Field(default=0, ge=0)
    upstream_issues_count: int = Field(default=0, ge=0)

    root_causes: list[ServiceImpactRootCauseSchema] = Field(default_factory=list)
    explanation: ServiceImpactExplanationSchema | None = None
    blast_radius: ServiceBlastRadiusSchema | None = None

    cycle_detected: bool = False
    depth_limited: bool = False


class ServiceImpactV2ResponseSchema(ApiModel):
    """Full Service Impact v2 response contract."""

    version: int = Field(default=2)
    items: list[ServiceImpactV2ItemSchema] = Field(default_factory=list)

    summary: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)


SERVICE_ANALYTICS_SORT_PATTERN = (
    r"^(service|open_alert_groups|critical_open_alert_groups|"
    r"raw_alerts|dedup_ratio|mtta|mttr|blast_radius)$"
)

SERVICE_ANALYTICS_ORDER_PATTERN = r"^(asc|desc)$"


class ServiceAnalyticsQuerySchema(ApiModel):
    """Validate Service Analytics v2 query."""

    team_id: int | None = Field(default=None, ge=1)
    service_id: int | None = Field(default=None, ge=1)

    days: int = Field(default=30, ge=1, le=365)
    include_disabled: bool = False
    include_operational: bool = True
    include_series: bool = True
    include_noise: bool = True
    include_response: bool = True
    include_maintenance: bool = True
    include_impact: bool = True

    limit: int = Field(default=100, ge=1, le=500)

    sort: str = Field(
        default="open_alert_groups",
        pattern=SERVICE_ANALYTICS_SORT_PATTERN,
    )
    order: str = Field(
        default="desc",
        pattern=SERVICE_ANALYTICS_ORDER_PATTERN,
    )
