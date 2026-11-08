"""Apply Google's terminal incident state before processing webhook deliveries."""

from app.modules.db.incident_core_repo import write_transaction
from app.modules.db.models import ClosedGoogleMonitoringIncident
from app.services.alerts.explain import (
    AlertExplainTrace,
    resolve_alert_explain_trace_level,
)
from app.services.alerts.lifecycle import upsert_alert
from app.services.alerts.reopen import lock_grouping_identity
from app.services.alerts.result import AlertProcessingResult


def process_google_monitoring_alert(event):
    """Serialize one provider incident, including a close delivered before open."""
    route_id = event["forced_route_id"]
    key = event["dedup_key"]
    is_close = event["status"] == "resolved"
    with write_transaction():
        lock_grouping_identity(
            source="google_cloud_monitoring",
            group_key=key,
            team_id=event["forced_team_id"],
            route_id=route_id,
            service_id=None,
        )
        if ClosedGoogleMonitoringIncident.get_or_none(
            ClosedGoogleMonitoringIncident.dedup_key == key
        ):
            reason = "Google Cloud Monitoring already closed this incident."
            trace = AlertExplainTrace.start(
                event, level=resolve_alert_explain_trace_level()
            )
            trace.stopped(outcome="ignored", reason=reason, result={"created": False})
            return AlertProcessingResult(
                outcome="ignored",
                processing_status="stopped",
                reason=reason,
                trace=trace,
            )

        result = upsert_alert(event)
        if is_close and (
            result.alert is not None
            and result.alert.status == "resolved"
            or result.outcome in {"ignored", "resolved_before_activation"}
        ):
            ClosedGoogleMonitoringIncident.create(dedup_key=key, route=route_id)
        return result
