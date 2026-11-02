"""Strict, bounded sender input; resolution never changes its identity digest."""

import json
import math
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.api.schemas.base import ApiModel

PositiveId = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
Name = Annotated[str, Field(min_length=1, max_length=255)]
Slug = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9_-]*$")
]
ServiceSlug = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9-]*$")
]
MAX_BODY_BYTES = 262144


class StrictInput(ApiModel):
    """Reject coercions and unknown fields without changing submitted strings."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)


class ServiceReference(StrictInput):
    """An ID or a slug, optionally qualified by one Team identity."""

    service_id: PositiveId | None = None
    service_slug: ServiceSlug | None = None
    team_id: PositiveId | None = None
    team_slug: Slug | None = None

    @model_validator(mode="after")
    def identities(self):
        if (self.service_id is None) == (self.service_slug is None):
            raise ValueError("Supply exactly one Service identity")
        if self.team_id is not None and self.team_slug is not None:
            raise ValueError("Supply at most one Team identity")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Omit unused identities instead of sending null")
        return self


class Actor(StrictInput):
    """Sender-provided attribution, never an authorization principal."""

    type: Annotated[str, Field(min_length=1, max_length=64)]
    name: Name


class ChangeEventInput(StrictInput):
    """A single event; omitted projection fields differ from explicit clears."""

    schema_version: Literal[1]
    event_id: Name
    change_id: Name
    source: Name
    owner_team_id: PositiveId | None = None
    owner_team_slug: Slug | None = None
    kind: Literal[
        "deployment",
        "configuration",
        "infrastructure",
        "database",
        "feature_flag",
        "other",
    ]
    event_type: Literal[
        "change.started",
        "change.updated",
        "change.succeeded",
        "change.failed",
        "change.rolled_back",
        "change.cancelled",
    ]
    occurred_at: datetime
    source_sequence: (
        Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)] | None
    ) = None
    environment: Name | None = None
    title: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(max_length=10000)] | None = None
    external_url: Annotated[str, Field(max_length=2048)] | None = None
    actor: Actor | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    changed_services: list[ServiceReference] = Field(
        default_factory=list, max_length=100
    )
    affected_services: list[ServiceReference] = Field(
        default_factory=list, max_length=100
    )
    changed_service_ids: list[PositiveId] = Field(default_factory=list, max_length=100)
    affected_service_ids: list[PositiveId] = Field(default_factory=list, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def portable_json(cls, value):
        """Reject text neither PostgreSQL nor canonical UTF-8 JSON can store."""
        pending = [(value, 0)]
        nodes = 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if nodes > 5000 or depth > 15:
                raise ValueError("Payload exceeds structural limits")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
                pending.extend((key, depth + 1) for key in item)
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif isinstance(item, str):
                if "\x00" in item:
                    raise ValueError("NUL characters are not supported")
                try:
                    item.encode("utf-8")
                except UnicodeError as error:
                    raise ValueError("Invalid Unicode text") from error
        return value

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def event_time(cls, value):
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
            value,
        ):
            raise ValueError(
                "Use an ISO 8601 timestamp with timezone and at most six fractional digits"
            )
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        except OverflowError as error:
            raise ValueError("Timestamp is outside the supported UTC range") from error

    @field_validator("external_url")
    @classmethod
    def safe_url(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Use an HTTP(S) URL without credentials")
            if any(ord(char) < 33 for char in value):
                raise ValueError("Invalid URL characters")
        return value

    @field_validator("details")
    @classmethod
    def bounded_details(cls, value):
        pending = [(value, 0)]
        nodes = 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if nodes > 2000 or depth > 10:
                raise ValueError("Details exceed nesting or node limits")
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("JSON object keys must be strings")
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif not (item is None or type(item) in {str, int, bool, float}):
                raise ValueError("Details must contain JSON values")
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Non-finite numbers are not JSON")
        if (
            len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            > 65536
        ):
            raise ValueError("Details exceed 64 KiB")
        return value

    @model_validator(mode="after")
    def validate_forms(self):
        if (self.owner_team_id is None) == (self.owner_team_slug is None):
            raise ValueError("Supply exactly one owner Team identity")
        for name in (
            "owner_team_id",
            "owner_team_slug",
            "source_sequence",
            "title",
            "actor",
        ):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError("Omit unused optional fields instead of sending null")
        for name in ("source", "event_id", "change_id", "title", "environment"):
            value = getattr(self, name)
            if value is not None and (not value.strip() or "\x00" in value):
                raise ValueError("Identity and title must contain text")
        for relation in ("changed", "affected"):
            if {
                f"{relation}_services",
                f"{relation}_service_ids",
            } <= self.model_fields_set:
                raise ValueError("Do not combine shortcut and structured references")
        if (
            sum(
                len(getattr(self, name))
                for name in (
                    "changed_services",
                    "affected_services",
                    "changed_service_ids",
                    "affected_service_ids",
                )
            )
            > 100
        ):
            raise ValueError("At most 100 Service references are allowed")
        return self

    def submitted_content(self):
        """Canonicalize syntactic sets, preserving explicit metadata updates."""
        data = self.model_dump(mode="json", exclude_unset=True)
        data["occurred_at"] = self.occurred_at.isoformat(timespec="microseconds")
        data["environment"] = self.environment
        for relation in ("changed", "affected"):
            refs = data.pop(f"{relation}_services", [])
            refs.extend(
                {"service_id": value}
                for value in data.pop(f"{relation}_service_ids", [])
            )
            normalized = {
                json.dumps(ref, sort_keys=True, separators=(",", ":")) for ref in refs
            }
            data[f"{relation}_services"] = [
                json.loads(ref) for ref in sorted(normalized)
            ]
        return data
