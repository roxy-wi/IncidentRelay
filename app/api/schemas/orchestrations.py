"""Request schemas for Event Orchestration control-plane APIs."""

from typing import Any, Dict, Literal

from pydantic import Field, field_validator, model_validator

from app.api.schemas.base import ApiModel
from app.services.integrations.normalizers.registry import (
    SUPPORTED_NORMALIZER_SOURCES,
)


class OrchestrationCreateSchema(ApiModel):
    group_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8192)
    scope: Literal["global", "service"] = "global"
    service_id: int | None = Field(default=None, ge=1)
    compatibility_mode: Literal["legacy", "hybrid", "orchestration"] = "legacy"

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "global" and self.service_id is not None:
            raise ValueError("global orchestration cannot reference a service")
        if self.scope == "service" and self.service_id is None:
            raise ValueError("service-scoped orchestration requires service_id")
        return self


class OrchestrationUpdateSchema(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8192)
    scope: Literal["global", "service"] | None = None
    service_id: int | None = Field(default=None, ge=1)


class OrchestrationDraftSchema(ApiModel):
    rules: list[Dict[str, Any]] = Field(default_factory=list, max_length=512)
    comment: str | None = Field(default=None, max_length=8192)


class OrchestrationPublishSchema(ApiModel):
    comment: str | None = Field(default=None, max_length=8192)
    confirm_catch_all_drop: bool = False


class OrchestrationRollbackSchema(ApiModel):
    version_id: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=8192)
    confirm_catch_all_drop: bool = False


class OrchestrationRuntimeSchema(ApiModel):
    mode: Literal["active", "shadow", "disabled"]
    compatibility_mode: Literal["legacy", "hybrid", "orchestration"] = "legacy"

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled"


class OrchestrationSimulationSchema(ApiModel):
    source: str | None = Field(default=None, max_length=128)
    payload: Any | None = None
    headers: Dict[str, Any] = Field(default_factory=dict)
    normalized_event: Dict[str, Any] | None = None
    event_index: int = Field(default=0, ge=0, le=1000)
    version_id: int | None = Field(default=None, ge=1)
    compare_with_active: bool = False

    @field_validator("source")
    @classmethod
    def validate_source(cls, value):
        if value is None:
            return None
        source = value.strip().lower()
        if source not in SUPPORTED_NORMALIZER_SOURCES:
            raise ValueError("unsupported simulation source")
        return source

    @model_validator(mode="after")
    def validate_input_mode(self):
        has_normalized = self.normalized_event is not None
        has_payload = self.payload is not None
        if has_normalized == has_payload:
            raise ValueError(
                "provide exactly one of normalized_event or payload"
            )
        if has_payload and not self.source:
            raise ValueError("source is required when payload is provided")
        return self


class OrchestrationReplaySchema(ApiModel):
    alert_ids: list[int] = Field(default_factory=list)
    execution_ids: list[int] = Field(default_factory=list)
    version_id: int | None = Field(default=None, ge=1)
    compare_with_active: bool = False

    @field_validator("alert_ids", "execution_ids")
    @classmethod
    def validate_ids(cls, value):
        result = []
        for raw in value:
            item = int(raw)
            if item < 1:
                raise ValueError("ids must be greater than 0")
            if item not in result:
                result.append(item)
        return result

    @model_validator(mode="after")
    def require_inputs(self):
        if not self.alert_ids and not self.execution_ids:
            raise ValueError(
                "at least one alert_id or execution_id is required"
            )
        return self


class OrchestrationWebhookActionCreateSchema(ApiModel):
    group_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8192)
    url: str = Field(min_length=1, max_length=4096)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    headers: Dict[str, Any] = Field(default_factory=dict)
    body_template: str | None = Field(default=None, max_length=65536)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    retry_count: int = Field(default=2, ge=0, le=10)
    private_network_policy: Literal["deny", "allowlist"] = "deny"
    enabled: bool = True


class OrchestrationWebhookActionUpdateSchema(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8192)
    url: str | None = Field(default=None, min_length=1, max_length=4096)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    headers: Dict[str, Any] | None = None
    body_template: str | None = Field(default=None, max_length=65536)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    retry_count: int | None = Field(default=None, ge=0, le=10)
    private_network_policy: Literal["deny", "allowlist"] | None = None
    enabled: bool | None = None
