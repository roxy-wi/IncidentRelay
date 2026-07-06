from datetime import datetime
from typing import Optional

from pydantic import Field, model_validator

from app.api.schemas.base import ApiModel


SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$"
BUSINESS_SERVICE_STATUS_PATTERN = (
    r"^(unknown|operational|degraded|partial_outage|major_outage|maintenance)$"
)
BUSINESS_SERVICE_CRITICALITY_PATTERN = r"^(critical|important|optional)$"
BUSINESS_SERVICE_TIER_PATTERN = r"^(tier_1|tier_2|tier_3|tier_4)$"

COMPONENT_TYPE_PATTERN = r"^(technical_service)$"
COMPONENT_CRITICALITY_PATTERN = r"^(required|critical|important|optional|informational)$"
COMPONENT_STATUS_RULE_PATTERN = r"^(inherit)$"

BUSINESS_SERVICE_MANUAL_STATUS_PATTERN = r"^(operational|degraded|partial_outage|major_outage|maintenance)$"


class BusinessServiceManualStatusSchema(ApiModel):
    status: str = Field(..., pattern=BUSINESS_SERVICE_MANUAL_STATUS_PATTERN)
    message: Optional[str] = Field(default=None, max_length=2000)
    until: Optional[datetime] = None


class BusinessServiceBaseSchema(ApiModel):
    """Validate business service input."""

    group_id: int = Field(ge=1)
    owner_team_id: int | None = Field(default=None, ge=1)

    slug: str = Field(min_length=1, max_length=64, pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)

    criticality: str = Field(default="important", pattern=BUSINESS_SERVICE_CRITICALITY_PATTERN)
    tier: str = Field(default="tier_2", pattern=BUSINESS_SERVICE_TIER_PATTERN)

    public: bool = True
    public_name: str | None = Field(default=None, max_length=255)
    public_description: str | None = Field(default=None, max_length=5000)
    public_order: int = Field(default=100, ge=0)

    labels: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    enabled: bool = True

    @model_validator(mode="after")
    def normalize_text(self):
        self.slug = self.slug.strip().lower()
        self.name = self.name.strip()

        if self.description is not None:
            self.description = self.description.strip()

        if self.public_name is not None:
            self.public_name = self.public_name.strip()

        if self.public_description is not None:
            self.public_description = self.public_description.strip()

        return self


class BusinessServiceCreateSchema(BusinessServiceBaseSchema):
    """Validate business service creation payload."""


class BusinessServiceUpdateSchema(BusinessServiceBaseSchema):
    """Validate business service update payload."""


class BusinessServiceComponentBaseSchema(ApiModel):
    """Validate business service component input."""

    service_id: int = Field(ge=1)
    component_type: str = Field(default="technical_service", pattern=COMPONENT_TYPE_PATTERN)
    criticality: str = Field(default="required", pattern=COMPONENT_CRITICALITY_PATTERN)
    impact_weight: int = Field(default=100, ge=0, le=100)
    position: int = Field(default=0, ge=0)
    status_rule: str = Field(default="inherit", pattern=COMPONENT_STATUS_RULE_PATTERN)
    description: str | None = Field(default=None, max_length=5000)
    enabled: bool = True

    @model_validator(mode="after")
    def normalize_text(self):
        if self.description is not None:
            self.description = self.description.strip()

        return self


class BusinessServiceComponentCreateSchema(BusinessServiceComponentBaseSchema):
    """Validate business service component creation payload."""


class BusinessServiceComponentUpdateSchema(BusinessServiceComponentBaseSchema):
    """Validate business service component update payload."""
