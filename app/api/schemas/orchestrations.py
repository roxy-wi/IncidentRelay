"""Request schemas for Event Orchestration simulation and replay."""

from typing import Any, Dict

from pydantic import Field, field_validator, model_validator

from app.api.schemas.base import ApiModel
from app.services.integrations.normalizers.registry import (
    SUPPORTED_NORMALIZER_SOURCES,
)


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
