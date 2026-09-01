import logging
import uuid

from app.modules.common import utc_now
from app.modules.db import alerts_repo

logger = logging.getLogger("oncall.alerts.explain")

TRACE_LEVEL_FULL = "full"
TRACE_LEVEL_COMPACT = "compact"
TRACE_LEVEL_DISABLED = "disabled"
EFFECTIVE_TRACE_LEVELS = {
    TRACE_LEVEL_FULL,
    TRACE_LEVEL_COMPACT,
    TRACE_LEVEL_DISABLED,
}


def normalize_alert_explain_trace_level(value, *, default=TRACE_LEVEL_FULL):
    level = str(value or "").strip().lower()
    if level in EFFECTIVE_TRACE_LEVELS:
        return level
    return default


def resolve_alert_explain_trace_level(override=None):
    """Resolve orchestration override against the global alert default."""
    if override is not None:
        level = str(override or "").strip().lower()
        if level in EFFECTIVE_TRACE_LEVELS:
            return level
        logger.warning(
            "invalid orchestration explain trace level; using global default",
            extra={"extra": {"explain_trace_level": level}},
        )

    from app import Config

    configured = str(
        getattr(Config, "ALERT_EXPLAIN_TRACE_LEVEL", TRACE_LEVEL_FULL)
        or TRACE_LEVEL_FULL
    ).strip().lower()
    if configured not in EFFECTIVE_TRACE_LEVELS:
        logger.warning(
            "invalid global explain trace level; using full",
            extra={"extra": {"explain_trace_level": configured}},
        )
        return TRACE_LEVEL_FULL
    return configured



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


def _normalize_severity(value):
    """Return canonical severity used in explain output."""
    severity = str(value or "").strip().lower()

    aliases = {
        "fatal": "critical",
        "disaster": "critical",
        "error": "high",
        "warn": "warning",
        "notice": "info",
        "informational": "info",
    }

    return aliases.get(severity, severity or None)


class AlertExplainTrace:
    """Explain trace for one alert processing run.

    Lifecycle processing starts in buffered mode so global Event Orchestration
    can choose the effective trace level before any trace rows are written.
    """

    def __init__(
        self,
        *,
        mode="live",
        source=None,
        dedup_key=None,
        input_summary=None,
        level=TRACE_LEVEL_FULL,
        buffered=False,
    ):
        self.trace_id = uuid.uuid4().hex
        self.position = 0
        self.row = None
        self.trace_level = None

        self._mode = mode
        self._source = source
        self._dedup_key = dedup_key
        self._input_summary = input_summary or {}
        self._started_at = utc_now()
        self._buffered = bool(buffered)
        self._applied = False
        self._disabled = False
        self._pending_steps = []
        self._pending_group = None
        self._pending_alert = None
        self._pending_finish = None

        if not self._buffered:
            self.apply_level(level)

    @classmethod
    def start(
        cls,
        alert_data,
        *,
        mode="live",
        level=TRACE_LEVEL_FULL,
        buffered=False,
    ):
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
            level=level,
            buffered=buffered,
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

    @classmethod
    def start_buffered(cls, alert_data, *, mode="live"):
        return cls.start(alert_data, mode=mode, buffered=True)

    def _stored_data(self, value):
        if self.trace_level == TRACE_LEVEL_COMPACT:
            return {}
        return value or {}

    def apply_level(self, level):
        """Commit buffered trace data according to the effective level."""
        if self._applied:
            return self

        level = normalize_alert_explain_trace_level(level)
        self.trace_level = level
        self._applied = True
        self._buffered = False

        if level == TRACE_LEVEL_DISABLED:
            self._disabled = True
            self.trace_id = None
            self._pending_steps.clear()
            self._pending_finish = None
            self._pending_group = None
            self._pending_alert = None
            return self

        self.row = alerts_repo.create_alert_explain_trace(
            trace_id=self.trace_id,
            mode=self._mode,
            source=self._source,
            dedup_key=self._dedup_key,
            trace_level=level,
            input_summary=self._stored_data(self._input_summary),
            started_at=self._started_at,
        )

        for item in self._pending_steps:
            try:
                alerts_repo.create_alert_explain_step(
                    trace=self.row,
                    position=item["position"],
                    stage=item["stage"],
                    code=item["code"],
                    status=item["status"],
                    title=item["title"],
                    message=item["message"],
                    data=self._stored_data(item["data"]),
                    created_at=item["created_at"],
                )
            except Exception:
                logger.exception(
                    "failed to create buffered alert explain step",
                    extra={
                        "extra": {
                            "trace_id": self.trace_id,
                            "stage": item["stage"],
                            "code": item["code"],
                        }
                    },
                )
        self._pending_steps.clear()

        if self._pending_group is not None or self._pending_alert is not None:
            try:
                self.row = alerts_repo.attach_alert_explain_trace(
                    self.row,
                    group=self._pending_group,
                    alert=self._pending_alert,
                )
            except Exception:
                logger.exception(
                    "failed to attach buffered alert explain trace",
                    extra={
                        "extra": {
                            "trace_id": self.trace_id,
                            "group_id": _obj_id(self._pending_group),
                            "alert_id": _obj_id(self._pending_alert),
                        }
                    },
                )

        if self._pending_finish is not None:
            finish = self._pending_finish
            try:
                self.row = alerts_repo.finish_alert_explain_trace(
                    self.row,
                    status=finish["status"],
                    outcome=finish["outcome"],
                    reason=finish["reason"],
                    result=self._stored_data(finish["result"]),
                    finished_at=finish["finished_at"],
                )
            except Exception:
                logger.exception(
                    "failed to finish buffered alert explain trace",
                    extra={
                        "extra": {
                            "trace_id": self.trace_id,
                            "outcome": finish["outcome"],
                        }
                    },
                )
            self._pending_finish = None

        return self

    def step(
        self,
        stage,
        code,
        step_status,
        title,
        message=None,
        **data,
    ):
        if self._disabled:
            return None

        self.position += 1
        created_at = utc_now()

        if self.row is None:
            self._pending_steps.append(
                {
                    "position": self.position,
                    "stage": stage,
                    "code": code,
                    "status": step_status,
                    "title": title,
                    "message": message,
                    "data": data,
                    "created_at": created_at,
                }
            )
            return None

        try:
            return alerts_repo.create_alert_explain_step(
                trace=self.row,
                position=self.position,
                stage=stage,
                code=code,
                status=step_status,
                title=title,
                message=message,
                data=self._stored_data(data),
                created_at=created_at,
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
        if self._disabled:
            return self

        if self.row is None:
            if group is not None:
                self._pending_group = group
            if alert is not None:
                self._pending_alert = alert
            return self

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
        if self._disabled:
            return self

        finished_at = utc_now()
        finish = {
            "status": status,
            "outcome": outcome,
            "reason": reason,
            "result": result or {},
            "finished_at": finished_at,
        }

        if self.row is None:
            self._pending_finish = finish
            return self

        try:
            self.row = alerts_repo.finish_alert_explain_trace(
                self.row,
                status=status,
                outcome=outcome,
                reason=reason,
                result=self._stored_data(result or {}),
                finished_at=finished_at,
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

    def priority_resolution_resolved(self, resolution, *, severity=None):
        priority = getattr(resolution, "priority", None)
        data = resolution.to_dict() if resolution else {}
        source = data.get("source")

        messages = {
            "source_priority": "Explicit priority supplied by the alert source was selected.",
            "policy_rule": "Priority was selected by the first matching priority policy rule.",
            "fixed_fallback": "No policy rule matched, so the fixed fallback priority was selected.",
            "severity_mapping": "Priority was selected from alert severity.",
            "unresolved": "Priority policy did not produce a priority.",
        }

        self.step(
            "priority",
            "priority_resolution",
            "success" if priority else "warning",
            "Priority resolved" if priority else "Priority was not resolved",
            messages.get(source, "Priority resolution completed."),
            severity=severity,
            normalized_severity=_normalize_severity(severity),
            **data,
        )

    def priority_applied(
            self,
            group,
            resolution,
            *,
            previous_priority_slug=None,
            previous_priority_order=None,
            created_group=False,
    ):
        current_priority_slug = getattr(group, "priority_slug", None)
        current_priority_order = getattr(group, "priority_order", None)
        manually_set = bool(
            getattr(group, "priority_set_manually", False)
        )

        update_mode = getattr(resolution, "update_mode", None)
        incoming_priority = getattr(resolution, "priority", None)
        incoming_priority_slug = getattr(
            incoming_priority,
            "slug",
            None,
        )
        incoming_priority_order = getattr(
            incoming_priority,
            "level",
            None,
        )

        if created_group:
            action = "initialized"
            message = (
                "Resolved priority was assigned when the incident "
                "was created."
            )

        elif manually_set:
            action = "manual_priority_preserved"
            message = (
                "Automatic priority was ignored because the incident "
                "priority was set manually."
            )

        elif update_mode == "initial_only":
            action = "initial_only_skipped"
            message = (
                "Automatic priority update was skipped because the "
                "policy only applies during incident creation."
            )

        elif previous_priority_slug != current_priority_slug:
            if update_mode == "recalculate":
                action = "recalculated"
                message = (
                    "Incident priority was recalculated from active alerts."
                )
            else:
                action = "raised"
                message = (
                    "Incident priority was raised automatically."
                )

        elif update_mode == "recalculate":
            action = "recalculated_unchanged"
            message = (
                "Priority was recalculated from active alerts, but the "
                "result was unchanged."
            )

        elif not incoming_priority_slug:
            action = "priority_unresolved"
            message = (
                "Automatic priority was not changed because priority "
                "resolution produced no priority."
            )

        elif (
                previous_priority_order is not None
                and incoming_priority_order is not None
                and incoming_priority_order > previous_priority_order
        ):
            action = "less_severe_skipped"
            message = (
                "The incoming priority was less severe than the current "
                "incident priority, so the incident was not downgraded."
            )

        elif (
                previous_priority_order is not None
                and incoming_priority_order is not None
                and incoming_priority_order == previous_priority_order
        ):
            action = "same_priority_skipped"
            message = (
                "The incoming priority matched the current incident "
                "priority."
            )

        else:
            action = "unchanged"
            message = (
                "Resolved priority did not change the incident priority."
            )

        successful_actions = {
            "initialized",
            "raised",
            "recalculated",
            "recalculated_unchanged",
        }

        self.step(
            "priority",
            "priority_application",
            "success" if action in successful_actions else "skipped",
            (
                "Priority applied"
                if action in {"initialized", "raised", "recalculated"}
                else "Priority unchanged"
            ),
            message,
            action=action,
            update_mode=update_mode,
            policy_id=getattr(resolution, "policy_id", None),
            policy_source=getattr(
                resolution,
                "policy_source",
                None,
            ),
            rule_id=getattr(resolution, "rule_id", None),
            resolution_source=getattr(resolution, "source", None),
            incoming_priority_slug=incoming_priority_slug,
            incoming_priority_order=incoming_priority_order,
            previous_priority_slug=previous_priority_slug,
            previous_priority_order=previous_priority_order,
            priority_slug=current_priority_slug,
            priority_order=current_priority_order,
            priority_set_manually=manually_set,
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
