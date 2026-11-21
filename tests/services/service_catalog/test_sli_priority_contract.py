"""API and calculation must agree on every accepted SLI priority scope."""

from types import SimpleNamespace

import pytest
from openapi_schema_validator import OAS30Validator
from pydantic import ValidationError

from app.api.openapi.endpoints.service_catalog import SERVICE_SLI_INPUT_SCHEMA
from app.api.schemas.services import ServiceSliCreateSchema, ServiceSliUpdateSchema
from app.modules.service_sli import PRIORITY_VALUES, normalize_priority_scope
from app.services.service_catalog.sli_slo import priority_scope_for_sli


@pytest.mark.parametrize("schema", [ServiceSliCreateSchema, ServiceSliUpdateSchema])
@pytest.mark.parametrize("value", [*PRIORITY_VALUES, " P1 ", "P2", "p9", "", None, 1, False])
def test_api_and_evaluation_accept_exactly_the_same_scope_values(schema, value):
    payload = {
        "slug": "scope-test", "name": "Scope test", "sli_type": "alert_ack_latency",
        "configuration": {"priority_scope": [value]},
    }
    stored = SimpleNamespace(**payload, priority=None)
    if str(value or "").strip().lower() not in PRIORITY_VALUES:
        with pytest.raises(ValidationError, match="priority_scope values must be one of"):
            schema.model_validate(payload)
        with pytest.raises(ValueError, match="priority_scope values must be one of"):
            priority_scope_for_sli(stored)
    else:
        validated = schema.model_validate(payload)
        expected = [str(value).strip().lower()]
        assert validated.configuration["priority_scope"] == expected
        assert priority_scope_for_sli(stored) == expected
        assert priority_scope_for_sli(validated) == expected


@pytest.mark.parametrize("scope,priority,sli_type,expected", [
    (None, None, "alert_ack_latency", []),
    ([], "p3", "alert_resolve_latency", []),
    (None, "p3", "alert_resolve_latency", ["p3"]),
    (None, None, "incident_availability", ["p1", "p2"]),
    (None, "p4", "incident_count", ["p4"]),
    ([" P2 ", "p1", "P2"], "p4", "incident_count", ["p2", "p1"]),
    (" P3 ", None, "alert_ack_latency", ["p3"]),
])
def test_scope_defaults_and_order_are_preserved(scope, priority, sli_type, expected):
    assert normalize_priority_scope(scope, sli_type=sli_type, priority=priority) == expected
    validated = ServiceSliCreateSchema.model_validate({
        "slug": "scope-test", "name": "Scope test", "sli_type": sli_type,
        "priority": priority,
        "configuration": {"priority_scope": scope, "other_setting": "preserved"},
    })
    assert priority_scope_for_sli(validated) == expected
    assert validated.configuration["other_setting"] == "preserved"


@pytest.mark.parametrize("scope", [123, {"priority": "p1"}, ["p1", "unknown"]])
def test_invalid_scope_shapes_and_mixed_values_are_rejected(scope):
    with pytest.raises(ValueError):
        normalize_priority_scope(scope, sli_type="incident_count")
    with pytest.raises(ValidationError):
        ServiceSliCreateSchema.model_validate({
            "slug": "bad", "name": "Bad", "sli_type": "incident_count",
            "configuration": {"priority_scope": scope},
        })


@pytest.mark.parametrize("priority", [*PRIORITY_VALUES, None, "p0", "p5", "P1", "critical"])
def test_legacy_priority_field_matches_published_values(priority):
    payload = {"slug": "legacy", "name": "Legacy", "sli_type": "alert_ack_latency", "priority": priority}
    allowed = SERVICE_SLI_INPUT_SCHEMA["properties"]["priority"]["enum"]
    validator = OAS30Validator(SERVICE_SLI_INPUT_SCHEMA["properties"]["priority"])
    assert validator.is_valid(priority) == (priority in allowed)
    if priority in allowed:
        validated = ServiceSliCreateSchema.model_validate(payload)
        assert priority_scope_for_sli(validated) == ([priority] if priority else [])
    else:
        with pytest.raises(ValidationError):
            ServiceSliCreateSchema.model_validate(payload)
