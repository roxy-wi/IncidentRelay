from dataclasses import dataclass


@dataclass
class AlertProcessingResult:
    group: object | None = None
    alert: object | None = None
    created_group: bool = False

    outcome: str = "unknown"
    processing_status: str = "completed"
    reason: str | None = None

    trace: object | None = None

    @property
    def trace_id(self):
        return getattr(self.trace, "trace_id", None)

    @property
    def group_id(self):
        return getattr(self.group, "id", None)

    @property
    def alert_id(self):
        return getattr(self.alert, "id", None)

    def as_dict(self):
        return {
            "created": self.created_group,
            "group_id": self.group_id,
            "alert_id": self.alert_id,
            "outcome": self.outcome,
            "processing_status": self.processing_status,
            "reason": self.reason,
            "trace_id": self.trace_id,
        }
