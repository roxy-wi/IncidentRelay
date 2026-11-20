"""Declarative Jira Data Center / Insight catalog configuration."""

from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.services.sync.directory.config import Operation, StrictModel, SyncConfig


class CatalogSelection(StrictModel):
    """Select objects with AQL and attributes by their ID or exact name."""

    query: str = Field(min_length=1, max_length=8000)
    owner_team_attribute: str | None = Field(default=None, max_length=255)
    name_attribute: str | None = Field(default=None, max_length=255)
    description_attribute: str | None = Field(default=None, max_length=255)
    fallback_description_attribute: str | None = Field(default=None, max_length=255)
    environment_attribute: str | None = Field(default=None, max_length=255)
    criticality_attribute: str | None = Field(default=None, max_length=255)
    status_attribute: str | None = Field(default=None, max_length=255)


class CmdbConfig(StrictModel):
    """Keep catalog imports separate from team and duty configuration."""

    source_type: Literal["jira_assets"] = "jira_assets"
    base_url: str
    private_network_policy: Literal["deny", "allowlist"] = "deny"
    verify_tls: bool = Field(default=True, strict=True)
    timeout_seconds: int = Field(default=30, ge=1, le=60)
    interval_seconds: int = Field(default=3600, ge=60, le=604800)
    api_path: str = "/rest/assets/1.0/aql/objects"
    query_parameter: Literal["qlQuery", "iql"] = "qlQuery"
    page_size: int = Field(default=25, ge=1, le=1000)
    max_pages: int = Field(default=1000, ge=1, le=1000)
    services: CatalogSelection
    business_services: CatalogSelection
    relationship_side: Literal["services", "business_services"] = "services"
    relationship_attribute: str | None = Field(default="Product", max_length=255)
    team_matches: dict[str, Annotated[int, Field(strict=True, ge=1)]] = Field(default_factory=dict)
    environment_values: dict[str, Literal["production", "staging", "development", "testing", "shared"]] = Field(
        default_factory=lambda: {"Prod": "production", "Stage": "staging", "Dev": "development", "Test": "testing"},
    )
    criticality_values: dict[str, Literal["low", "medium", "high", "critical"]] = Field(
        default_factory=lambda: {"Business Critical": "critical"},
    )
    business_criticality_values: dict[str, Literal["critical", "important", "optional"]] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value):
        return SyncConfig.validate_base_url(value)

    @field_validator("api_path")
    @classmethod
    def valid_path(cls, value):
        Operation.relative_path(value)
        if "?" in value:
            raise ValueError("Put AQL in the object selection, not in the API path")
        return value

    @field_validator("team_matches")
    @classmethod
    def valid_matches(cls, value):
        if any(not key.isdecimal() or int(key) < 1 or local_id < 1 for key, local_id in value.items()):
            raise ValueError("Team matches must use positive CMDB object IDs and IR team IDs")
        return value

    @property
    def operations(self):
        """Use the shared bounded, DNS-pinned, credential-safe HTTP transport."""
        return {kind: Operation(path=self.api_path, params={
            "includeAttributes": "true", "includeTypeAttributes": "true", "includeAttributesDeep": 1,
        }) for kind in ("services", "business_services")}

    def import_settings(self):
        """Operational settings do not change a reviewed catalog plan."""
        return self.model_dump(exclude={
            "interval_seconds", "timeout_seconds", "verify_tls", "private_network_policy", "page_size", "max_pages",
        })


def is_cmdb(config):
    """Identify catalog sources while retaining compatibility with legacy configs."""
    return config.get("source_type") == "jira_assets"


def parse_config(config):
    """Validate persisted configuration with the source-specific contract."""
    return (CmdbConfig if is_cmdb(config) else SyncConfig).model_validate(config)


def jira_assets_preset():
    """Editable defaults; no installation-specific IDs are embedded."""
    return CmdbConfig(
        base_url="https://jira.example.com",
        services=CatalogSelection(
            query='objectType = "System"', owner_team_attribute="SRE Support Team",
            description_attribute="Description", environment_attribute="Environment",
            criticality_attribute="Criticality", status_attribute="Environment Status",
        ),
        business_services=CatalogSelection(
            query='objectType = "Product"', owner_team_attribute="Product Support Team",
            description_attribute="Long Description", fallback_description_attribute="Short Description",
            status_attribute="Status",
        ),
    ).model_dump()
