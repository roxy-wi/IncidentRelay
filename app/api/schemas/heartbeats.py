from typing import Any, Dict, List

from pydantic import ConfigDict, Field, model_validator

from app.api.schemas.base import ApiModel


HEARTBEAT_MODE_PATTERN = r"^(interval|scheduled)$"
HEARTBEAT_STATUS_PATTERN = r"^(new|ok|overdue|paused)$"
HEARTBEAT_SCHEDULE_KIND_PATTERN = r"^(daily|weekly|monthly)$"
HEARTBEAT_SEVERITY_PATTERN = r"^(critical|high|medium|warning|low|info)$"
HEARTBEAT_PRIORITY_PATTERN = r"^p[1-5]$"
HEARTBEAT_EXPECTED_INSTANCES_MODE_PATTERN = r"^(none|static|auto)$"


class HeartbeatBaseSchema(ApiModel):
    team_id: int = Field(ge=1)
    route_id: int = Field(ge=1)
    service_id: int | None = Field(default=None, ge=1)

    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str | None = Field(default=None, max_length=2000)

    mode: str = Field(default="interval", pattern=HEARTBEAT_MODE_PATTERN)
    expected_interval_seconds: int | None = Field(default=300, ge=30, le=31536000)
    grace_period_seconds: int = Field(default=300, ge=0, le=31536000)

    schedule_kind: str | None = Field(default=None, pattern=HEARTBEAT_SCHEDULE_KIND_PATTERN)
    schedule_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_weekday: int | None = Field(default=None, ge=0, le=6)
    schedule_monthday: int | None = Field(default=None, ge=1, le=31)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    severity: str = Field(default="critical", pattern=HEARTBEAT_SEVERITY_PATTERN)
    priority_slug: str = Field(default="p2", pattern=HEARTBEAT_PRIORITY_PATTERN)

    enabled: bool = True
    auto_resolve: bool = True

    instance_tracking_enabled: bool = False
    instance_key: str = Field(default="instance", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_instances_mode: str = Field(default="none", pattern=HEARTBEAT_EXPECTED_INSTANCES_MODE_PATTERN)
    expected_instances: List[str] = Field(default_factory=list)
    auto_discovery_ttl_days: int | None = Field(default=30, ge=1, le=3650)

    labels: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode_fields(self):
        if not self.instance_tracking_enabled:
            self.expected_instances_mode = "none"
            self.expected_instances = []
            self.auto_discovery_ttl_days = None
        elif self.expected_instances_mode == "static" and not self.expected_instances:
            raise ValueError("expected_instances is required when static instance tracking is enabled")
        elif self.expected_instances_mode == "none":
            raise ValueError("expected_instances_mode must be static or auto when instance tracking is enabled")

        if self.mode == "interval":
            if not self.expected_interval_seconds:
                raise ValueError("expected_interval_seconds is required for interval heartbeats")
            self.schedule_kind = None
            self.schedule_time = None
            self.schedule_weekday = None
            self.schedule_monthday = None
            return self

        if not self.schedule_kind:
            raise ValueError("schedule_kind is required for scheduled heartbeats")
        if not self.schedule_time:
            raise ValueError("schedule_time is required for scheduled heartbeats")
        if self.schedule_kind == "weekly" and self.schedule_weekday is None:
            raise ValueError("schedule_weekday is required for weekly heartbeats")
        if self.schedule_kind == "monthly" and self.schedule_monthday is None:
            raise ValueError("schedule_monthday is required for monthly heartbeats")

        self.expected_interval_seconds = None
        return self


class HeartbeatCreateSchema(HeartbeatBaseSchema):
    pass


class HeartbeatUpdateSchema(HeartbeatBaseSchema):
    status: str | None = Field(default=None, pattern=HEARTBEAT_STATUS_PATTERN)


class HeartbeatPingSchema(ApiModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    status: str | None = Field(default="completed", max_length=64)
    run_id: str | None = Field(default=None, max_length=255)
    instance: str | None = Field(default=None, max_length=255)
    host: str | None = Field(default=None, max_length=255)
    hostname: str | None = Field(default=None, max_length=255)
    node: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=2000)
    payload: Dict[str, Any] = Field(default_factory=dict)
