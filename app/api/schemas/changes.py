"""Bounded read filters; private fields only filter owner-visible Changes."""

from datetime import timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.api.schemas.base import ApiModel

QueryId = Annotated[int, Field(gt=0, le=2147483647)]


class InvalidChangeQuery(ValueError):
    """A malformed or contradictory read selector."""


class ChangePageQuery(ApiModel):
    """Use the application's page pagination with a bounded page size."""

    page: Annotated[int, Field(ge=1, le=1000000)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 25


class ChangeQuery(ChangePageQuery):
    """Resolve a Service filter only inside the reader's permitted namespace."""

    search: Annotated[str, Field(max_length=200)] = ""
    owner_team_id: QueryId | None = None
    scope_team_id: QueryId | None = None
    service_id: QueryId | None = None
    service_slug: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    team_id: QueryId | None = None
    team_slug: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    source: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    environment: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    kind: (
        Literal[
            "deployment",
            "configuration",
            "infrastructure",
            "database",
            "feature_flag",
            "other",
        ]
        | None
    ) = None
    status: (
        Literal["unknown", "running", "succeeded", "failed", "rolled_back", "cancelled"]
        | None
    ) = None
    occurred_from: AwareDatetime | None = None
    occurred_to: AwareDatetime | None = None

    @field_validator("occurred_from", "occurred_to", mode="before")
    @classmethod
    def iso_timestamp(cls, value):
        """Query timestamps require an explicit ISO date, time and timezone."""
        if value is not None and (not isinstance(value, str) or "T" not in value):
            raise ValueError("Use an ISO timestamp with a timezone")
        return value

    @model_validator(mode="after")
    def coherent_filters(self):
        """Reject ambiguous identities and backwards time windows."""
        if self.service_id is not None and self.service_slug is not None:
            raise ValueError("Supply only one Service identity")
        if self.team_id is not None and self.team_slug is not None:
            raise ValueError("Supply only one Team namespace")
        namespace = self.team_id is not None or self.team_slug is not None
        if bool(self.service_slug) != namespace:
            raise ValueError("A Service slug requires exactly one Team namespace")
        if (
            self.occurred_from
            and self.occurred_to
            and self.occurred_from > self.occurred_to
        ):
            raise ValueError("Invalid time range")
        for name in ("occurred_from", "occurred_to"):
            value = getattr(self, name)
            if value:
                setattr(self, name, value.astimezone(timezone.utc).replace(tzinfo=None))
        return self
