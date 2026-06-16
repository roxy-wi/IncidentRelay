from typing import Any, Dict, List

from pydantic import Field, field_validator, model_validator

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
    matchers: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True

    @model_validator(mode="after")
    def validate_matchers(self):
        """Require at least one matcher."""
        if not self.matchers:
            raise ValueError("Service match rule must have at least one matcher")
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

    title: str = Field(
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
    )
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )
    url: str = Field(min_length=3, max_length=2048)
    severity: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    matchers: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0)
    enabled: bool = True


class ServiceRunbookCreateSchema(ServiceRunbookBaseSchema):
    """Validate service runbook creation."""


class ServiceRunbookUpdateSchema(ServiceRunbookBaseSchema):
    """Validate service runbook update."""


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


class ServiceImpactPathNodeSchema(ApiModel):
    """Service node inside an impact path."""

    service_id: int = Field(ge=1)
    service_slug: str | None = None
    service_name: str | None = None
    status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
    effective_status: str = Field(pattern=SERVICE_IMPACT_STATUS_PATTERN)
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
    severity: str | None = None
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
