"""Strict inputs for integration administration and audited configuration edits."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from app.api.schemas.base import ApiModel

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Name = Annotated[str, Field(min_length=1, max_length=255)]


class IntegrationCreate(ApiModel):
    """Create a named machine principal."""

    name: Name
    owner_group_id: PositiveId | None = None
    owner_team_id: PositiveId


class RevisionInput(ApiModel):
    """Prevent silent overwrites of a stale permissions screen."""

    expected_revision: PositiveId


class IntegrationUpdate(RevisionInput):
    """Only name and activity may change."""

    name: Name | None = None
    active: StrictBool | None = None

    @model_validator(mode="after")
    def require_edit(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, name) is None for name in fields):
            raise ValueError("Supply at least one non-null field")
        return self


class SourceCreate(RevisionInput):
    """Reserve a sender's source string in its owner's namespace."""

    owner_team_id: PositiveId
    source: Name
    ordering_mode: Literal["timestamp", "sequence"] = "timestamp"


class SourceUpdate(RevisionInput):
    """Source identity may change only before its first Change."""

    source: Name | None = None
    owner_team_id: PositiveId | None = None
    active: StrictBool | None = None
    ordering_mode: Literal["timestamp", "sequence"] | None = None

    @model_validator(mode="after")
    def require_edit(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, name) is None for name in fields):
            raise ValueError("Supply at least one non-null field")
        return self


class GrantCreate(RevisionInput):
    """One capability for a Team (including future Services) or one Service."""

    capability: Literal["reference", "changed", "reported_affected"]
    target_team_id: PositiveId
    target_service_id: PositiveId | None = None


class GrantUpdate(RevisionInput):
    """Edit a permission explicitly; null Service means the whole Team."""

    source_id: PositiveId | None = None
    capability: Literal["reference", "changed", "reported_affected"] | None = None
    target_team_id: PositiveId | None = None
    target_service_id: PositiveId | None = None
    active: StrictBool | None = None

    @model_validator(mode="after")
    def require_edit(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(
            getattr(self, name) is None for name in fields - {"target_service_id"}
        ):
            raise ValueError("Supply at least one valid field")
        return self


class MachineTokenCreate(RevisionInput):
    """The server fixes identity and scopes; only lifetime and name are input."""

    name: Name
    days: Annotated[int, Field(strict=True, ge=1, le=3650)] = 90
