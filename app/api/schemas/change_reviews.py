"""Explicit manual decisions with optimistic concurrency and an audit reason."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.base import ApiModel
from app.api.schemas.changes import ChangePageQuery, QueryId

Relation = Literal["context", "potential_cause", "confirmed_cause", "mitigation"]
Version = Annotated[int, Field(strict=True, gt=0)]
Note = Annotated[str, Field(min_length=1, max_length=2000)]


class CorrelationCreate(ApiModel):
    """Record a manual relation even without an automatic candidate."""

    episode_id: QueryId
    relation_type: Relation
    note: Note


class CorrelationReview(ApiModel):
    """Confirm/reject the version the operator actually read."""

    row_version: Version
    decision: Literal["confirmed", "rejected"]
    relation_type: Relation
    note: Note
    evidence_version: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    manual: bool = False


class IncidentChangeCreate(ApiModel):
    """The previous link version is required when restoring a removed link."""

    change_uid: UUID
    relation_type: Relation = "context"
    row_version: Version | None = None
    note: Note


class IncidentChangeUpdate(ApiModel):
    """Change a role without overwriting another operator's decision."""

    row_version: Version
    relation_type: Relation
    note: Note


class IncidentChangeRemove(ApiModel):
    """Soft deletion retains the immutable audit and protects investigation data."""

    row_version: Version
    note: Note


class ReviewTargetQuery(ChangePageQuery):
    """Search only authorized existing episodes; never reconstruct old ones."""

    search: Annotated[str, Field(max_length=200)] = ""


class IncidentChangeQuery(ChangePageQuery):
    """Removed links can be read explicitly to obtain their restore version."""

    include_removed: bool = False
