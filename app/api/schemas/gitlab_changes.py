"""The native Deployment Hook contract; unrelated GitLab fields are ignored."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.change_events import ChangeEventInput, Name

GitLabProjectId = Annotated[int, Field(strict=True, gt=0, le=9007199254740991)]
GitLabDeploymentId = Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]


class GitLabObject(BaseModel):
    """Allow vendor additions without coercing identity fields."""

    model_config = ConfigDict(extra="ignore", strict=True)


class GitLabProject(GitLabObject):
    """Stable project identity and display metadata."""

    id: GitLabProjectId
    path_with_namespace: Annotated[str, Field(max_length=500)] | None = None


class GitLabUser(GitLabObject):
    """Attribution only, never an IR authorization principal."""

    name: Name | None = None
    username: Name | None = None


class GitLabDeployment(GitLabObject):
    """Normalize timestamps so retries do not depend on delivery time or headers."""

    object_kind: Literal["deployment"]
    project: GitLabProject
    deployment_id: GitLabDeploymentId
    environment: Name
    status: Literal[
        "running", "success", "failed", "canceled", "blocked", "approved", "rejected"
    ]
    status_changed_at: datetime
    deployable_url: Annotated[str, Field(max_length=2048)] | None = None
    short_sha: Annotated[str, Field(max_length=64)] | None = None
    user: GitLabUser | None = None

    @field_validator("status_changed_at", mode="before")
    @classmethod
    def timestamp(cls, value):
        return ChangeEventInput.event_time(value)

    @field_validator("deployable_url")
    @classmethod
    def safe_url(cls, value):
        return ChangeEventInput.safe_url(value)

    def change_event(self, source, service_ids, event_id):
        """Translate vendor state without treating approval rejection as failure."""
        lifecycle = {
            "running": "change.started",
            "success": "change.succeeded",
            "failed": "change.failed",
            "canceled": "change.cancelled",
        }
        body = {
            "schema_version": 1,
            "source": source.source,
            "owner_team_id": source.owner_team_id,
            "change_id": f"gitlab:{self.project.id}:{self.deployment_id}",
            "event_id": event_id,
            "kind": "deployment",
            "event_type": lifecycle.get(self.status, "change.updated"),
            "occurred_at": self.status_changed_at.isoformat(),
            "environment": self.environment,
            "title": (
                f"{self.project.path_with_namespace or self.project.id} / "
                f"{self.environment} / deployment {self.deployment_id}"
            )[:500],
            "changed_service_ids": service_ids,
            "details": {
                "gitlab_project_id": self.project.id,
                "gitlab_deployment_id": self.deployment_id,
                "gitlab_status": self.status,
                "short_sha": self.short_sha,
            },
        }
        if self.deployable_url:
            body["external_url"] = self.deployable_url
        if self.user and (self.user.name or self.user.username):
            body["actor"] = {
                "type": "user",
                "name": self.user.name or self.user.username,
            }
        return ChangeEventInput.model_validate(body)
