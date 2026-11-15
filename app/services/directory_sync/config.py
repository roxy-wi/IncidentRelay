"""Validated, declarative HTTP operations and field mappings (no executable code)."""

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SyncError(ValueError):
    """A safe, actionable synchronization error without response bodies or secrets."""


class SyncBusy(SyncError):
    """Another worker owns the live lease; keep queued work intact."""


class SyncApiError(SyncError):
    """An upstream API failure, distinct from a local synchronization conflict."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Pagination(StrictModel):
    mode: Literal["none", "cursor", "offset", "page"] = "none"
    parameter: str = "pageToken"
    next_path: str = "nextPageToken"
    size_parameter: str = "pageSize"
    size: int = Field(default=100, ge=1, le=1000)
    start: int = Field(default=0, ge=0)
    max_pages: int = Field(default=1000, ge=1, le=1000)


class Operation(StrictModel):
    method: Literal["GET", "POST"] = "GET"
    path: str
    params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    items: str = ""
    pagination: Pagination = Field(default_factory=Pagination)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value):
        if not value.startswith("/") or value.startswith("//") or "#" in value:
            raise ValueError("Use an API path starting with one slash")
        return value


class Collection(StrictModel):
    path: str
    fields: dict[str, Any]


class SyncConfig(StrictModel):
    base_url: str
    private_network_policy: Literal["deny", "allowlist"] = "deny"
    verify_tls: bool = Field(
        default=True, strict=True,
        description="Verify the TLS certificate and hostname for this source's API requests.",
    )
    interval_seconds: int = Field(default=3600, ge=60, le=604800)
    current_interval_seconds: int = Field(default=60, ge=10, le=3600)
    current_max_age_seconds: int = Field(default=120, ge=10, le=3600)
    horizon_months: int = Field(default=2, ge=1, le=11)
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    editable: bool = False
    overwrite_existing: bool = False
    delete_missing: bool = False
    membership_authority: Literal["sync", "oidc"] = "sync"
    member_role: Literal["viewer", "responder", "manager"] = "responder"
    responsible_role: Literal["viewer", "responder", "manager"] = "manager"
    group_role: Literal["viewer", "editor", "user_admin"] = "viewer"
    user_fetch: Literal["per_user", "all"] = "per_user"
    current_fetch: Literal["batch", "per_schedule"] = "batch"
    operations: dict[str, Operation]
    team_fields: dict[str, Any]
    detail_fields: dict[str, Any] = Field(default_factory=dict)
    team_filter: str | None = None
    members: Collection
    responsible: Collection | None = None
    schedules: Collection
    shift_fields: dict[str, Any]
    replacements: Collection
    user_fields: dict[str, Any]
    current_fields: dict[str, Any] = Field(default_factory=dict)
    # Explicit external-team -> existing IR team matches, reviewed in preview.
    team_matches: dict[str, int] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Use an HTTP(S) base URL without credentials, query or fragment")
        return value.rstrip("/")

    @field_validator("operations")
    @classmethod
    def operation_names(cls, value):
        if not {"teams", "shifts"}.issubset(value):
            raise ValueError("teams and shifts operations are required")
        if set(value) - {"teams", "team", "user", "shifts", "current"}:
            raise ValueError("Unknown operation")
        return value


def path_value(data, path, *, default=None):
    """Read a dotted field path, numeric array index or the whole value ($)."""
    if path in ("", "$"):
        return data
    current = data
    for part in str(path).removeprefix("$.").split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return default
    return current


def map_fields(data, fields):
    """Map paths or explicit {value: ...}/{path: ..., default: ...} descriptors."""
    result = {}
    for name, spec in fields.items():
        if isinstance(spec, str):
            result[name] = path_value(data, spec)
        elif isinstance(spec, dict) and "value" in spec:
            result[name] = spec["value"]
        elif isinstance(spec, dict) and "path" in spec:
            value = path_value(data, spec["path"], default=spec.get("default"))
            if "values" in spec:
                value = spec["values"].get(str(value), spec.get("default"))
            result[name] = value
        elif isinstance(spec, dict) and "join" in spec and isinstance(spec.get("paths"), list):
            result[name] = str(spec["join"]).join(str(path_value(data, path) or "").strip()
                                                 for path in spec["paths"] if path_value(data, path))
        else:
            raise SyncError(f"Invalid mapping for {name}")
    return result


def org_service_preset():
    """Return an editable example for the supplied org-service OnCall contract."""
    person = {"id": "employeeUuid", "username": "username", "name": "displayName",
              "inactive": "inactive"}
    return SyncConfig(
        base_url="https://org-service.example.com",
        operations={
            "teams": Operation(path="/api/v1/support-team-catalog", items="teams",
                               pagination=Pagination(mode="cursor")),
            "team": Operation(path="/api/v1/duty-scopes/{team_id}"),
            "user": Operation(path="/api/v1/employees", params={"uuid": "{user_id}"},
                              items="employees"),
            "shifts": Operation(path="/api/v1/duty-scopes/{team_id}/shifts",
                                params={"from": "{from}", "to": "{to}"}, items="shifts"),
            "current": Operation(method="POST", path="/api/v1/duty-schedules:batch-current",
                                 body={"scheduleUuids": "{schedule_ids}"}, items="duties"),
        },
        team_fields={"id": "enrolledScopeUuid", "name": "name", "description": "description"},
        team_filter="enrolledScopeUuid",
        detail_fields={"name": "name", "description": "description", "enabled": "enabled"},
        members=Collection(path="roster", fields={key: "person." + value for key, value in person.items()}),
        responsible=Collection(path="responsible", fields=person),
        schedules=Collection(path="schedules", fields={"id": "uuid", "timezone": "timezone"}),
        shift_fields={"id": "uuid", "schedule_id": "scheduleUuid", "user_id": "employee.employeeUuid",
                      "start": "startAt", "end": "endAt", "title": "title",
                      "unavailable": "availabilityConflict", "inactive": "employee.inactive"},
        replacements=Collection(path="replacements", fields={
            "id": "uuid", "user_id": "employee.employeeUuid", "start": "startAt", "end": "endAt",
            "precedence": "precedence", "inactive": "employee.inactive",
        }),
        user_fields={"id": "uuid", "username": "username", "email": "email", "phone": "contactPhone",
                     "name": {"paths": ["firstname", "lastname"], "join": " "}},
        current_fields={"id": "scheduleUuid", "user_id": "currentEmployeeUuid", "status": "status",
                        "valid_until": "validUntil", "start": "effectiveStart", "end": "effectiveEnd"},
    ).model_dump()
