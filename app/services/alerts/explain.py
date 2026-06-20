import logging
import uuid

from app.modules.db import alerts_repo

logger = logging.getLogger("oncall.alerts.explain")


def _obj_id(obj):
    return getattr(obj, "id", None)


def _obj_name(obj):
    return (
        getattr(obj, "name", None)
        or getattr(obj, "slug", None)
        or getattr(obj, "username", None)
    )


def _iso(value):
    return value.isoformat() if value else None


class AlertExplainTrace:
    """Explain trace for one alert processing run."""

    def __init__(
        self,
        *,
        mode="live",
        source=None,
        dedup_key=None,
        input_summary=None,
    ):
        self.trace_id = uuid.uuid4().hex
        self.position = 0

        self.row = alerts_repo.create_alert_explain_trace(
            trace_id=self.trace_id,
            mode=mode,
            source=source,
            dedup_key=dedup_key,
            input_summary=input_summary or {},
        )

    @classmethod
    def start(cls, alert_data, *, mode="live"):
        trace = cls(
            mode=mode,
            source=alert_data.get("source"),
            dedup_key=alert_data.get("dedup_key"),
            input_summary={
                "source": alert_data.get("source"),
                "status": alert_data.get("status") or "firing",
                "title": alert_data.get("title"),
                "severity": alert_data.get("severity"),
                "dedup_key": alert_data.get("dedup_key"),
                "team_slug": alert_data.get("team_slug"),
                "labels": alert_data.get("labels") or {},
            },
        )

        trace.step(
            "received",
            "alert_received",
            "success",
            "Alert received",
            "Incoming alert accepted by normalizer.",
            source=alert_data.get("source"),
            status=alert_data.get("status") or "firing",
            severity=alert_data.get("severity"),
            dedup_key=alert_data.get("dedup_key"),
        )

        return trace

    def step(
            self,
            stage,
            code,
            step_status,
            title,
            message=None,
            **data,
    ):
        self.position += 1

        try:
            return alerts_repo.create_alert_explain_step(
                trace=self.row,
                position=self.position,
                stage=stage,
                code=code,
                status=step_status,
                title=title,
                message=message,
                data=data,
            )
        except Exception:
            logger.exception(
                "failed to create alert explain step",
                extra={
                    "extra": {
                        "trace_id": self.trace_id,
                        "stage": stage,
                        "code": code,
                    }
                },
            )

            return None

    def attach(self, *, group=None, alert=None):
        try:
            self.row = alerts_repo.attach_alert_explain_trace(
                self.row,
                group=group,
                alert=alert,
            )
        except Exception:
            logger.exception(
                "failed to attach alert explain trace",
                extra={
                    "extra": {
                        "trace_id": self.trace_id,
                        "group_id": _obj_id(group),
                        "alert_id": _obj_id(alert),
                    }
                },
            )

        return self

    def finish(
        self,
        *,
        status="completed",
        outcome=None,
        reason=None,
        result=None,
    ):
        try:
            self.row = alerts_repo.finish_alert_explain_trace(
                self.row,
                status=status,
                outcome=outcome,
                reason=reason,
                result=result or {},
            )
        except Exception:
            logger.exception(
                "failed to finish alert explain trace",
                extra={
                    "extra": {
                        "trace_id": self.trace_id,
                        "outcome": outcome,
                    }
                },
            )

        return self

    def fail(self, exc):
        self.step(
            "result",
            "processing_exception",
            "error",
            "Alert processing failed",
            exc.__class__.__name__,
            exception_type=exc.__class__.__name__,
        )

        return self.finish(
            status="failed",
            outcome="failed",
            reason="Alert processing failed.",
            result={
                "exception_type": exc.__class__.__name__,
            },
        )

    def route_not_matched(self, alert_data):
        self.step(
            "route",
            "route_not_matched",
            "error",
            "No route matched",
            "Alert did not match any active route.",
            team_slug=alert_data.get("team_slug"),
            routing_error=alert_data.get("routing_error"),
        )

    def route_matched(self, route, team=None):
        self.step(
            "route",
            "route_matched",
            "success",
            "Route matched",
            route_id=_obj_id(route),
            route_name=_obj_name(route),
            team_id=_obj_id(team or getattr(route, "team", None)),
            team_slug=getattr(team or getattr(route, "team", None), "slug", None),
        )

    def service_resolved(self, service):
        self.step(
            "service",
            "service_matched" if service else "service_not_matched",
            "success" if service else "skipped",
            "Service matched" if service else "No service matched",
            service_id=_obj_id(service),
            service_slug=getattr(service, "slug", None),
            service_name=_obj_name(service),
        )

    def rotation_resolved(self, rotation):
        self.step(
            "rotation",
            "rotation_selected" if rotation else "rotation_missing",
            "success" if rotation else "warning",
            "Rotation selected" if rotation else "No effective rotation selected",
            rotation_id=_obj_id(rotation),
            rotation_name=_obj_name(rotation),
        )

    def priority_resolved(self, priority, *, severity=None):
        self.step(
            "priority",
            "priority_resolved" if priority else "priority_defaulted",
            "success" if priority else "skipped",
            "Priority resolved" if priority else "Default priority selected",
            priority_id=_obj_id(priority),
            priority_slug=getattr(priority, "slug", None) or "p3",
            priority_order=getattr(priority, "level", None) or 3,
            severity=severity,
        )

    def group_key_built(self, group_key):
        self.step(
            "dedup",
            "group_key_built",
            "success",
            "Group key built",
            group_key=group_key,
        )

    def maintenance_resolved(self, decision):
        matched = bool(getattr(decision, "matched", False))
        window = getattr(decision, "window", None)

        self.step(
            "maintenance",
            "maintenance_matched" if matched else "maintenance_not_matched",
            "success" if matched else "skipped",
            "Maintenance window matched" if matched else "No maintenance window matched",
            window_id=_obj_id(window),
            window_name=_obj_name(window),
            behavior=getattr(decision, "behavior", None),
            incident_status=getattr(decision, "incident_status", None),
            suppress_incident=bool(getattr(decision, "suppress_incident", False)),
            suppress_notifications=bool(getattr(decision, "suppress_notifications", False)),
            pause_escalation_only=bool(getattr(decision, "pause_escalation_only", False)),
        )

    def incident_suppressed(self, decision):
        window = getattr(decision, "window", None)

        self.step(
            "maintenance",
            "incident_suppressed",
            "stopped",
            "Incident suppressed by maintenance",
            "No alert group was created because maintenance suppresses incidents.",
            window_id=_obj_id(window),
            window_name=_obj_name(window),
            behavior=getattr(decision, "behavior", None),
        )

    def dedup_completed(self, *, existing_alert=None, existing_group=None):
        self.step(
            "dedup",
            "dedup_lookup_completed",
            "success",
            "Deduplication lookup completed",
            existing_alert_id=_obj_id(existing_alert),
            existing_group_id=_obj_id(existing_group),
        )

    def existing_alert_found(self, alert, group=None):
        self.step(
            "dedup",
            "existing_alert_found",
            "success",
            "Existing alert found",
            alert_id=_obj_id(alert),
            group_id=_obj_id(group or getattr(alert, "group", None)),
            previous_status=getattr(alert, "status", None),
        )

    def policy_resolved(self, policy, rule=None):
        self.step(
            "policy",
            "policy_selected" if policy else "policy_missing",
            "success" if policy else "skipped",
            "Escalation policy selected" if policy else "No escalation policy selected",
            policy_id=_obj_id(policy),
            policy_name=_obj_name(policy),
            rule_id=_obj_id(rule),
            rule_position=getattr(rule, "position", None),
            rule_target_type=getattr(rule, "target_type", None),
        )

    def assignee_resolved(
        self,
        assignee,
        *,
        rotation=None,
        next_escalation_at=None,
    ):
        self.step(
            "assignment",
            "assignee_selected" if assignee else "assignee_missing",
            "success" if assignee else "warning",
            "Initial assignee selected" if assignee else "No initial assignee selected",
            assignee_id=_obj_id(assignee),
            assignee_username=getattr(assignee, "username", None),
            rotation_id=_obj_id(rotation),
            rotation_name=_obj_name(rotation),
            next_escalation_at=_iso(next_escalation_at),
        )

    def silence_resolved(self, silence):
        self.step(
            "silence",
            "silence_matched" if silence else "silence_not_matched",
            "success" if silence else "skipped",
            "Silence matched" if silence else "No silence matched",
            silence_id=_obj_id(silence),
            silence_name=_obj_name(silence),
        )

    def group_created(self, group):
        self.attach(group=group)

        self.step(
            "group",
            "group_created",
            "success",
            "Incident group created",
            group_id=_obj_id(group),
            group_key=getattr(group, "group_key", None),
            status=getattr(group, "status", None),
            priority=getattr(group, "priority_slug", None),
        )

    def group_created_for_existing_alert(self, group, alert):
        self.attach(group=group, alert=alert)

        self.step(
            "group",
            "group_created_for_existing_alert",
            "success",
            "Incident group created for existing alert",
            group_id=_obj_id(group),
            alert_id=_obj_id(alert),
            group_key=getattr(group, "group_key", None),
            status=getattr(group, "status", None),
        )

    def group_reused(self, group):
        self.attach(group=group)

        self.step(
            "group",
            "group_reused",
            "success",
            "Existing incident group reused",
            group_id=_obj_id(group),
            group_key=getattr(group, "group_key", None),
            status=getattr(group, "status", None),
        )

    def group_reopened(self, group):
        self.attach(group=group)

        self.step(
            "group",
            "group_reopened",
            "success",
            "Existing acknowledged incident reopened",
            group_id=_obj_id(group),
            group_key=getattr(group, "group_key", None),
            status=getattr(group, "status", None),
        )

    def alert_created(self, alert, group=None):
        self.attach(group=group or getattr(alert, "group", None), alert=alert)

        self.step(
            "alert",
            "alert_created",
            "success",
            "Child alert created",
            alert_id=_obj_id(alert),
            group_id=_obj_id(group or getattr(alert, "group", None)),
            status=getattr(alert, "status", None),
            dedup_key=getattr(alert, "dedup_key", None),
        )

    def alert_updated(self, alert, group=None, *, previous_status=None):
        self.attach(group=group or getattr(alert, "group", None), alert=alert)

        self.step(
            "alert",
            "existing_alert_updated",
            "success",
            "Existing alert updated",
            alert_id=_obj_id(alert),
            group_id=_obj_id(group or getattr(alert, "group", None)),
            previous_status=previous_status,
            status=getattr(alert, "status", None),
        )

    def alert_resolved(self, alert, group=None):
        self.step(
            "alert",
            "alert_resolved",
            "success",
            "Alert resolved by incoming payload",
            alert_id=_obj_id(alert),
            group_id=_obj_id(group or getattr(alert, "group", None)),
        )

    def routing_warning_recorded(self, routing_error):
        self.step(
            "route",
            "routing_warning_recorded",
            "warning",
            "Routing warning recorded",
            routing_error=routing_error,
        )

    def notification_scheduled(
        self,
        *,
        reason,
        group_wait_seconds=None,
        group_interval_seconds=None,
    ):
        self.step(
            "notification",
            "notification_scheduled",
            "scheduled",
            "Notification scheduled",
            reason=reason,
            group_wait_seconds=group_wait_seconds,
            group_interval_seconds=group_interval_seconds,
        )

    def notification_suppressed(self, *, behavior=None):
        self.step(
            "notification",
            "notification_suppressed",
            "skipped",
            "Notification suppressed",
            "Maintenance behavior suppressed notifications.",
            behavior=behavior,
        )

    def notification_not_needed(self, group):
        self.step(
            "notification",
            "notification_not_needed",
            "skipped",
            "Notification not needed",
            group_status=getattr(group, "status", None),
        )

    def resolved_notification_sent(self, *, sent_count):
        self.step(
            "notification",
            "resolved_notification_sent",
            "success" if sent_count else "warning",
            (
                "Resolved notification sent"
                if sent_count
                else "Resolved notification had no delivery target"
            ),
            sent_count=sent_count,
        )

    def orphan_resolved_ignored(self, alert_data):
        self.step(
            "result",
            "orphan_resolved_ignored",
            "stopped",
            "Orphan resolved alert ignored",
            "Resolved payload did not match an existing active alert.",
            source=alert_data.get("source"),
            dedup_key=alert_data.get("dedup_key"),
        )

    def processed(self, *, group=None, alert=None, created_group=False, outcome=None):
        outcome = outcome or ("created" if created_group else "added")

        self.step(
            "result",
            "alert_processed",
            "success",
            "Alert processed",
            group_id=_obj_id(group),
            alert_id=_obj_id(alert),
            created_group=created_group,
            group_status=getattr(group, "status", None),
        )

        self.finish(
            status="completed",
            outcome=outcome,
            result={
                "created": created_group,
                "group_id": _obj_id(group),
                "alert_id": _obj_id(alert),
                "group_status": getattr(group, "status", None),
            },
        )

    def updated(self, *, group=None, alert=None):
        self.step(
            "result",
            "alert_updated",
            "success",
            "Alert updated",
            group_id=_obj_id(group),
            alert_id=_obj_id(alert),
            group_status=getattr(group, "status", None),
        )

        self.finish(
            status="completed",
            outcome="updated",
            result={
                "created": False,
                "group_id": _obj_id(group),
                "alert_id": _obj_id(alert),
                "group_status": getattr(group, "status", None),
            },
        )

    def stopped(self, *, outcome, reason, result=None):
        self.finish(
            status="stopped",
            outcome=outcome,
            reason=reason,
            result=result or {},
        )
