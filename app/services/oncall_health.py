from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Iterable

from peewee import DoesNotExist

from app.modules.db import channels_repo, rotations_repo, routes_repo, teams_repo
from app.services.oncall import get_current_oncall_user
from app.modules.common import utc_now

DEFAULT_HEALTH_WINDOW_DAYS = 7
DEFAULT_HEALTH_SAMPLE_MINUTES = 60
MAX_HEALTH_GAP_ISSUES = 20

SEVERITY_ORDER = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}


@dataclass(frozen=True)
class HealthIssue:
    severity: str
    code: str
    title: str
    message: str
    target_type: str
    target_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    team_id: int | None = None
    team_slug: str | None = None
    rotation_id: int | None = None
    rotation_name: str | None = None
    layer_id: int | None = None
    layer_name: str | None = None
    user_id: int | None = None
    username: str | None = None
    hint: str | None = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "starts_at": serialize_health_datetime(self.starts_at),
            "ends_at": serialize_health_datetime(self.ends_at),
            "team_id": self.team_id,
            "team_slug": self.team_slug,
            "rotation_id": self.rotation_id,
            "rotation_name": self.rotation_name,
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "user_id": self.user_id,
            "username": self.username,
            "hint": self.hint,
        }


def utc_now_naive() -> datetime:
    return utc_now().replace(microsecond=0)


def as_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(microsecond=0)
    return value.astimezone(dt_timezone.utc).replace(tzinfo=None, microsecond=0)


def serialize_health_datetime(value: datetime | None) -> str | None:
    value = as_utc_naive(value)
    if value is None:
        return None
    return value.replace(tzinfo=dt_timezone.utc).isoformat().replace("+00:00", "Z")


def default_window(
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> tuple[datetime, datetime]:
    start = as_utc_naive(starts_at) or utc_now_naive()
    end = as_utc_naive(ends_at) or (start + timedelta(days=DEFAULT_HEALTH_WINDOW_DAYS))
    if end <= start:
        end = start + timedelta(days=DEFAULT_HEALTH_WINDOW_DAYS)
    return start, end


def summarize_issues(issues: Iterable[HealthIssue]) -> dict:
    issues = list(issues)
    critical = sum(1 for item in issues if item.severity == "critical")
    warning = sum(1 for item in issues if item.severity == "warning")
    info = sum(1 for item in issues if item.severity == "info")

    if critical:
        status = "critical"
        tooltip = f"Critical: {critical} · Warnings: {warning}"
    elif warning:
        status = "warning"
        tooltip = f"Warnings: {warning}"
    else:
        status = "ok"
        tooltip = "OK"

    return {
        "status": status,
        "critical": critical,
        "warning": warning,
        "info": info,
        "total": critical + warning + info,
        "tooltip": tooltip,
    }


def serialize_health_payload(
    scope: str,
    target,
    issues: list[HealthIssue],
    starts_at: datetime,
    ends_at: datetime,
) -> dict:
    sorted_issues = sorted(
        issues,
        key=lambda item: (
            SEVERITY_ORDER.get(item.severity, 99),
            item.starts_at or datetime.min,
            item.code,
        ),
    )

    payload = {
        "scope": scope,
        "window": {
            "starts_at": serialize_health_datetime(starts_at),
            "ends_at": serialize_health_datetime(ends_at),
        },
        "summary": summarize_issues(sorted_issues),
        "issues": [item.to_dict() for item in sorted_issues],
    }

    if scope == "rotation":
        payload.update({
            "rotation_id": target.id,
            "rotation_name": target.name,
            "team_id": target.team.id,
            "team_slug": target.team.slug,
            "team_name": target.team.name,
        })
    elif scope == "team":
        payload.update({
            "team_id": target.id,
            "team_slug": target.slug,
            "team_name": target.name,
        })

    return payload


def issue_for_rotation(rotation, severity: str, code: str, title: str, message: str, **kwargs) -> HealthIssue:
    return HealthIssue(
        severity=severity,
        code=code,
        title=title,
        message=message,
        target_type=kwargs.pop("target_type", "rotation"),
        target_id=kwargs.pop("target_id", rotation.id),
        team_id=rotation.team.id,
        team_slug=rotation.team.slug,
        rotation_id=rotation.id,
        rotation_name=rotation.name,
        **kwargs,
    )


def issue_for_team(team, severity: str, code: str, title: str, message: str, **kwargs) -> HealthIssue:
    return HealthIssue(
        severity=severity,
        code=code,
        title=title,
        message=message,
        target_type=kwargs.pop("target_type", "team"),
        target_id=kwargs.pop("target_id", team.id),
        team_id=team.id,
        team_slug=team.slug,
        **kwargs,
    )


def user_label(user) -> str:
    return getattr(user, "display_name", None) or getattr(user, "username", None) or f"user #{getattr(user, 'id', '-')}"


def user_has_deliverable_contact(user) -> bool:
    """Return True when a profile has at least one direct delivery target.

    This intentionally checks profile-level contact fields only. Channel/provider
    rule evaluation stays in notification services; health should be cheap and
    side-effect free.
    """
    if not user:
        return False
    if not getattr(user, "active", False) or getattr(user, "deleted", False):
        return False
    return bool(
        getattr(user, "email", None)
        or getattr(user, "phone", None)
        or getattr(user, "telegram_user_id", None)
        or getattr(user, "slack_user_id", None)
        or getattr(user, "mattermost_user_id", None)
    )


def list_enabled_team_channels(team_id: int):
    try:
        return channels_repo.list_channels(team_id=team_id, enabled_only=True)
    except Exception:
        return []


def list_enabled_team_routes(team_id: int):
    try:
        return routes_repo.list_routes(team_id=team_id, enabled_only=True)
    except Exception:
        return []


def route_channel_count(route) -> int:
    try:
        return len(routes_repo.list_route_channels(route.id))
    except Exception:
        return 0


def route_uses_rotation(route, rotation) -> bool:
    route_rotation_id = getattr(route, "rotation_id", None)
    if route_rotation_id is None and getattr(route, "rotation", None):
        route_rotation_id = getattr(route.rotation, "id", None)
    return int(route_rotation_id or 0) == int(rotation.id)


def rotation_has_enabled_route(rotation) -> bool:
    return any(route_uses_rotation(route, rotation) for route in list_enabled_team_routes(rotation.team.id))


def list_effective_layer_members(
    layer,
    starts_at: datetime,
    ends_at: datetime,
    *,
    include_inactive_users: bool,
):
    try:
        return rotations_repo.list_rotation_layer_member_periods(
            layer.id,
            start_at=starts_at,
            end_at=ends_at,
            include_inactive_users=include_inactive_users,
        )
    except AttributeError:
        return rotations_repo.list_rotation_layer_members(
            layer.id,
            active_only=True,
            at=starts_at,
            include_inactive_users=include_inactive_users,
        )


def check_rotation_structure(rotation, starts_at: datetime, ends_at: datetime) -> list[HealthIssue]:
    issues: list[HealthIssue] = []

    layers = rotations_repo.list_rotation_layers(rotation.id, enabled_only=False)
    enabled_layers = [
        layer for layer in layers
        if getattr(layer, "enabled", False) and not getattr(layer, "deleted", False)
    ]

    if not layers:
        issues.append(issue_for_rotation(
            rotation,
            "critical",
            "rotation_has_no_layers",
            "Rotation has no layers",
            "Add at least one enabled layer with users, cadence and coverage windows.",
            hint="Open rotation layers and create the first layer.",
        ))
        return issues

    if not enabled_layers:
        issues.append(issue_for_rotation(
            rotation,
            "critical",
            "rotation_has_no_enabled_layers",
            "Rotation has no enabled layers",
            "All layers are disabled, so the rotation cannot produce an on-call user.",
            hint="Enable a layer or create a new enabled layer.",
        ))

    unique_active_user_ids = set()
    for layer in enabled_layers:
        members = list_effective_layer_members(layer, starts_at, ends_at, include_inactive_users=True)
        active_members = [member for member in members if getattr(member, "active", False)]
        active_valid_members = [
            member for member in active_members
            if getattr(member, "user", None)
            and getattr(member.user, "active", False)
            and not getattr(member.user, "deleted", False)
        ]

        if not active_valid_members:
            issues.append(issue_for_rotation(
                rotation,
                "critical",
                "enabled_layer_has_no_members",
                "Enabled layer has no active members",
                f"Layer '{layer.name}' is enabled but has no active users in the checked window.",
                target_type="layer",
                target_id=layer.id,
                layer_id=layer.id,
                layer_name=layer.name,
                hint="Add active team users to this layer or disable it.",
            ))
            continue

        for member in active_valid_members:
            unique_active_user_ids.add(member.user.id)
            if not user_has_deliverable_contact(member.user):
                issues.append(issue_for_rotation(
                    rotation,
                    "warning",
                    "member_has_no_deliverable_notification",
                    "Layer member has no direct notification contact",
                    f"{user_label(member.user)} participates in layer '{layer.name}' but has no email, phone, Telegram, Slack or Mattermost identifier.",
                    target_type="user",
                    target_id=member.user.id,
                    layer_id=layer.id,
                    layer_name=layer.name,
                    user_id=member.user.id,
                    username=member.user.username,
                    hint="Ask the user to complete profile contacts or configure profile notification rules.",
                ))

        inactive_members = [
            member for member in active_members
            if getattr(member, "user", None)
            and (not getattr(member.user, "active", False) or getattr(member.user, "deleted", False))
        ]
        for member in inactive_members:
            issues.append(issue_for_rotation(
                rotation,
                "warning",
                "layer_has_inactive_members",
                "Layer contains inactive user",
                f"Layer '{layer.name}' contains inactive user {user_label(member.user)}.",
                target_type="user",
                target_id=member.user.id,
                layer_id=layer.id,
                layer_name=layer.name,
                user_id=member.user.id,
                username=member.user.username,
                hint="Remove inactive users from the layer or reactivate the user.",
            ))

    if len(unique_active_user_ids) == 1:
        issues.append(issue_for_rotation(
            rotation,
            "warning",
            "rotation_has_single_active_member",
            "Rotation has only one active member",
            "Only one user can be selected across enabled layers in the checked window.",
            hint="Add at least one more user to reduce single-person on-call risk.",
        ))

    return issues


def check_rotation_current_state(rotation, now: datetime) -> list[HealthIssue]:
    issues: list[HealthIssue] = []

    if not getattr(rotation, "enabled", False):
        if rotation_has_enabled_route(rotation):
            issues.append(issue_for_rotation(
                rotation,
                "critical",
                "rotation_disabled_but_used",
                "Disabled rotation is used by an enabled route",
                "At least one enabled alert route still points to this disabled rotation.",
                hint="Enable the rotation, change the route rotation, or disable the route.",
            ))
        else:
            issues.append(issue_for_rotation(
                rotation,
                "warning",
                "rotation_disabled",
                "Rotation is disabled",
                "This rotation does not participate in on-call scheduling while disabled.",
                hint="Enable the rotation when it should handle alerts.",
            ))
        return issues

    current_user = get_current_oncall_user(rotation, now)
    if not current_user:
        issues.append(issue_for_rotation(
            rotation,
            "critical",
            "no_current_oncall",
            "No current on-call user",
            "The rotation cannot resolve an assignee right now.",
            hint="Check enabled layers, restrictions, start date and members.",
        ))
        return issues

    if not getattr(current_user, "active", False) or getattr(current_user, "deleted", False):
        issues.append(issue_for_rotation(
            rotation,
            "critical",
            "current_oncall_user_inactive",
            "Current on-call user is inactive",
            f"{user_label(current_user)} is currently selected but the user is inactive or deleted.",
            target_type="user",
            target_id=current_user.id,
            user_id=current_user.id,
            username=current_user.username,
            hint="Remove inactive users from active layers or reactivate the user.",
        ))
    elif not user_has_deliverable_contact(current_user):
        issues.append(issue_for_rotation(
            rotation,
            "critical",
            "current_oncall_user_has_no_deliverable_notification",
            "Current on-call user has no direct notification contact",
            f"{user_label(current_user)} is currently on-call but has no email, phone, Telegram, Slack or Mattermost identifier.",
            target_type="user",
            target_id=current_user.id,
            user_id=current_user.id,
            username=current_user.username,
            hint="Ask the user to complete profile contacts or enable profile notification rules.",
        ))

    return issues


def check_rotation_schedule_gaps(
    rotation,
    starts_at: datetime,
    ends_at: datetime,
    sample_minutes: int = DEFAULT_HEALTH_SAMPLE_MINUTES,
) -> list[HealthIssue]:
    if not getattr(rotation, "enabled", False):
        return []

    step = timedelta(minutes=max(15, sample_minutes))
    cursor = starts_at
    gap_start = None
    issues: list[HealthIssue] = []

    while cursor < ends_at:
        user = get_current_oncall_user(rotation, cursor)
        has_user = bool(
            user
            and getattr(user, "active", False)
            and not getattr(user, "deleted", False)
        )

        if not has_user and gap_start is None:
            gap_start = cursor

        elif has_user and gap_start is not None:
            issues.append(issue_for_rotation(
                rotation,
                "critical",
                "schedule_gap",
                "Schedule gap detected",
                "No active on-call user can be resolved for part of the checked window.",
                starts_at=gap_start,
                ends_at=cursor,
                hint="Check layer restrictions, users and override windows.",
            ))
            gap_start = None

        cursor += step

    if gap_start is not None:
        issues.append(issue_for_rotation(
            rotation,
            "critical",
            "schedule_gap",
            "Schedule gap detected",
            "No active on-call user can be resolved for part of the checked window.",
            starts_at=gap_start,
            ends_at=ends_at,
            hint="Check layer restrictions, users and override windows.",
        ))

    merged_issues = merge_schedule_gap_issues(issues)

    if len(merged_issues) <= MAX_HEALTH_GAP_ISSUES:
        return merged_issues

    visible_issues = merged_issues[:MAX_HEALTH_GAP_ISSUES]
    visible_issues.append(issue_for_rotation(
        rotation,
        "warning",
        "schedule_gap_output_truncated",
        "More schedule gaps were found",
        (
            f"Only the first {MAX_HEALTH_GAP_ISSUES} schedule gaps are shown. "
            "Fix the listed gaps and run diagnostics again."
        ),
        hint="Reduce schedule gaps or run diagnostics for a shorter window.",
    ))

    return visible_issues


def merge_schedule_gap_issues(issues: list[HealthIssue]) -> list[HealthIssue]:
    if not issues:
        return []

    merged: list[HealthIssue] = []
    current = issues[0]
    for issue in issues[1:]:
        if current.ends_at and issue.starts_at and issue.starts_at <= current.ends_at:
            current = HealthIssue(
                severity=current.severity,
                code=current.code,
                title=current.title,
                message=current.message,
                target_type=current.target_type,
                target_id=current.target_id,
                starts_at=current.starts_at,
                ends_at=max(current.ends_at, issue.ends_at) if issue.ends_at else current.ends_at,
                team_id=current.team_id,
                team_slug=current.team_slug,
                rotation_id=current.rotation_id,
                rotation_name=current.rotation_name,
                layer_id=current.layer_id,
                layer_name=current.layer_name,
                user_id=current.user_id,
                username=current.username,
                hint=current.hint,
            )
            continue
        merged.append(current)
        current = issue
    merged.append(current)
    return merged


def check_rotation_supporting_resources(rotation, starts_at: datetime, ends_at: datetime) -> list[HealthIssue]:
    issues: list[HealthIssue] = []

    channels = list_enabled_team_channels(rotation.team.id)
    if not channels and list_enabled_team_routes(rotation.team.id):
        issues.append(issue_for_rotation(
            rotation,
            "warning",
            "team_has_no_enabled_channels",
            "Team has no enabled notification channels",
            "Enabled routes can send alerts to this team, but no team notification channels are enabled.",
            target_type="team",
            target_id=rotation.team.id,
            hint="Enable at least one channel or make sure profile notifications cover assigned users.",
        ))

    routes_using_rotation = [
        route for route in list_enabled_team_routes(rotation.team.id)
        if route_uses_rotation(route, rotation)
    ]
    for route in routes_using_rotation:
        if route_channel_count(route) == 0:
            issues.append(issue_for_rotation(
                rotation,
                "warning",
                "route_has_no_channels",
                "Enabled route has no channel links",
                f"Route '{route.name}' points to this rotation but has no linked channels.",
                target_type="route",
                target_id=route.id,
                hint="Link at least one channel to the route or rely on profile notifications intentionally.",
            ))

    return issues


def collect_rotation_health_issues(
    rotation,
    starts_at: datetime,
    ends_at: datetime,
    *,
    include_schedule_gaps: bool = True,
    sample_minutes: int = DEFAULT_HEALTH_SAMPLE_MINUTES,
) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    issues.extend(check_rotation_current_state(rotation, starts_at))
    issues.extend(check_rotation_structure(rotation, starts_at, ends_at))
    issues.extend(check_rotation_supporting_resources(rotation, starts_at, ends_at))
    if include_schedule_gaps:
        issues.extend(check_rotation_schedule_gaps(rotation, starts_at, ends_at, sample_minutes=sample_minutes))
    return issues


def check_rotation_health(
    rotation,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    *,
    include_schedule_gaps: bool = True,
    sample_minutes: int = DEFAULT_HEALTH_SAMPLE_MINUTES,
) -> dict:
    start, end = default_window(starts_at, ends_at)
    issues = collect_rotation_health_issues(
        rotation,
        start,
        end,
        include_schedule_gaps=include_schedule_gaps,
        sample_minutes=sample_minutes,
    )
    return serialize_health_payload("rotation", rotation, issues, start, end)


def get_rotation_health_summary(
    rotation,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> dict:
    """Return a cheap structural health summary suitable for table rows."""
    try:
        start, end = default_window(starts_at, ends_at)
        summary = summarize_issues(
            collect_rotation_summary_issues(rotation, start, end)
        )

        if summary["status"] == "ok":
            summary["tooltip"] = "OK · click for full diagnostics"
        else:
            summary["tooltip"] = (
                f'{summary["tooltip"]} · click for full diagnostics'
            )

        summary["partial"] = True
        return summary

    except Exception:
        return {
            "status": "unknown",
            "critical": 0,
            "warning": 0,
            "info": 0,
            "total": 0,
            "tooltip": "Health check failed",
            "partial": True,
        }


def collect_rotation_summary_issues(
    rotation,
    starts_at: datetime,
    ends_at: datetime,
) -> list[HealthIssue]:
    """Collect very cheap row-level health issues.

    This function is intentionally structural only.
    It must not call get_current_oncall_user(), schedule builders,
    notification delivery checks, route checks or any future-window scans.

    Full diagnostics are loaded only from the modal endpoint.
    """
    issues: list[HealthIssue] = []

    layers = list(getattr(rotation, "layers", []) or [])
    enabled_layers = [
        layer for layer in layers
        if getattr(layer, "enabled", True)
    ]

    if not getattr(rotation, "enabled", True):
        issues.append(HealthIssue(
            severity="warning",
            code="rotation_disabled",
            title="Rotation is disabled",
            message="This rotation is disabled and will not assign an on-call user.",
            target_type="rotation",
            target_id=getattr(rotation, "id", None),
        ))
        return issues

    if not layers:
        issues.append(HealthIssue(
            severity="critical",
            code="rotation_has_no_layers",
            title="Rotation has no layers",
            message="Enabled rotation has no schedule layers.",
            target_type="rotation",
            target_id=getattr(rotation, "id", None),
        ))
        return issues

    if not enabled_layers:
        issues.append(HealthIssue(
            severity="critical",
            code="rotation_has_no_enabled_layers",
            title="Rotation has no enabled layers",
            message="Rotation has layers, but all of them are disabled.",
            target_type="rotation",
            target_id=getattr(rotation, "id", None),
        ))
        return issues

    active_member_count = 0
    inactive_member_count = 0
    empty_layer_count = 0

    for layer in enabled_layers:
        members = list(getattr(layer, "members", []) or [])
        if not members:
            empty_layer_count += 1
            continue

        for member in members:
            user = getattr(member, "user", None)
            if user and getattr(user, "active", True):
                active_member_count += 1
            else:
                inactive_member_count += 1

    if empty_layer_count:
        issues.append(HealthIssue(
            severity="critical",
            code="enabled_layer_has_no_members",
            title="Enabled layer has no members",
            message=f"{empty_layer_count} enabled layer(s) have no members.",
            target_type="rotation",
            target_id=getattr(rotation, "id", None),
        ))

    if active_member_count == 0:
        issues.append(HealthIssue(
            severity="critical",
            code="rotation_has_no_active_members",
            title="Rotation has no active members",
            message="Enabled rotation has no active users in enabled layers.",
            target_type="rotation",
            target_id=getattr(rotation, "id", None),
        ))
    elif active_member_count == 1:
        issues.append(HealthIssue(
            severity="warning",
            code="rotation_has_single_active_member",
            title="Rotation has only one active member",
            message="Only one active user is available in enabled layers.",
            target_type="rotation",
            target_id=getattr(rotation, "id", None),
        ))

    if inactive_member_count:
        issues.append(HealthIssue(
            severity="warning",
            code="layer_has_inactive_members",
            title="Layer has inactive members",
            message=f"{inactive_member_count} inactive member(s) are still present in enabled layers.",
            target_type="rotation",
            target_id=getattr(rotation, "id", None),
        ))

    return issues


def collect_team_summary_issues(team) -> list[HealthIssue]:
    """Collect cheap row-level team health issues.

    This is only for Teams table indicators.
    Do not run schedule scans here.
    Do not call check_team_oncall_health() here.
    """
    issues: list[HealthIssue] = []

    if not getattr(team, "active", False):
        issues.append(issue_for_team(
            team,
            "warning",
            "team_disabled",
            "Team is disabled",
            "Disabled teams cannot receive active alert routing.",
            hint="Enable the team when it should receive alerts.",
        ))
        return issues

    rotations = rotations_repo.list_rotations(
        team_id=team.id,
        active_only=False,
    )
    enabled_rotations = [
        rotation for rotation in rotations
        if getattr(rotation, "enabled", False)
        and not getattr(rotation, "deleted", False)
    ]

    enabled_routes = list_enabled_team_routes(team.id)
    enabled_channels = list_enabled_team_channels(team.id)

    if not enabled_rotations:
        issues.append(issue_for_team(
            team,
            "critical",
            "team_has_no_active_rotation",
            "Team has no enabled rotations",
            "Alerts routed to this team cannot resolve a rotation assignee unless routes use another explicit target.",
            hint="Create and enable at least one rotation for this team.",
        ))

    if enabled_routes and not enabled_channels:
        issues.append(issue_for_team(
            team,
            "warning",
            "team_has_no_enabled_channels",
            "Team has no enabled notification channels",
            "Enabled routes can receive alerts, but no team notification channels are enabled.",
            hint="Enable at least one channel or intentionally rely on profile-level notifications.",
        ))

    for route in enabled_routes:
        route_rotation_id = getattr(route, "rotation_id", None)

        if not route_rotation_id:
            route_rotation = getattr(route, "rotation", None)
            route_rotation_id = getattr(route_rotation, "id", None)

        route_policy_id = getattr(route, "escalation_policy_id", None)

        if not route_policy_id:
            route_policy = getattr(route, "escalation_policy", None)
            route_policy_id = getattr(route_policy, "id", None)

        if not route_rotation_id and not route_policy_id:
            issues.append(issue_for_team(
                team,
                "warning",
                "route_has_no_assignment_target",
                "Enabled route has no assignment target",
                (
                    f"Route '{route.name}' can receive alerts but has neither "
                    "a rotation nor an escalation policy assigned."
                ),
                hint=(
                    "Attach a rotation or an escalation policy "
                    "that can resolve an assignee."
                ),
            ))

        if route_channel_count(route) == 0:
            issues.append(issue_for_team(
                team,
                "warning",
                "route_has_no_channels",
                "Enabled route has no channel links",
                f"Route '{route.name}' has no linked channels.",
                target_type="route",
                target_id=route.id,
                hint="Link at least one channel to the route.",
            ))

    for rotation in enabled_rotations:
        rotation_summary = get_rotation_health_summary(rotation)

        if rotation_summary.get("status") == "critical":
            issues.append(issue_for_team(
                team,
                "critical",
                "team_rotation_has_critical_health",
                "Rotation has critical health issues",
                f"Rotation '{rotation.name}' has critical health issues.",
                hint="Open rotation health diagnostics for details.",
            ))
        elif rotation_summary.get("status") == "warning":
            issues.append(issue_for_team(
                team,
                "warning",
                "team_rotation_has_warnings",
                "Rotation has health warnings",
                f"Rotation '{rotation.name}' has health warnings.",
                hint="Open rotation health diagnostics for details.",
            ))

    return issues


def get_team_health_summary(team) -> dict:
    """Return cheap team health summary suitable for Teams table rows."""
    try:
        summary = summarize_issues(collect_team_summary_issues(team))

        if summary["status"] == "ok":
            summary["tooltip"] = "OK · click for full diagnostics"
        else:
            summary["tooltip"] = (
                f'{summary["tooltip"]} · click for full diagnostics'
            )

        summary["partial"] = True
        return summary

    except Exception:
        return {
            "status": "unknown",
            "critical": 0,
            "warning": 0,
            "info": 0,
            "total": 0,
            "tooltip": "Team health check failed",
            "partial": True,
        }


def check_team_oncall_health(
    team,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    *,
    include_rotation_issues: bool = True,
    include_schedule_gaps: bool = True,
    sample_minutes: int = DEFAULT_HEALTH_SAMPLE_MINUTES,
) -> dict:
    start, end = default_window(starts_at, ends_at)
    issues: list[HealthIssue] = []

    rotations = rotations_repo.list_rotations(team_id=team.id, active_only=False)
    enabled_rotations = [
        rotation for rotation in rotations
        if getattr(rotation, "enabled", False) and not getattr(rotation, "deleted", False)
    ]
    enabled_routes = list_enabled_team_routes(team.id)
    enabled_channels = list_enabled_team_channels(team.id)

    if not enabled_rotations:
        issues.append(issue_for_team(
            team,
            "critical",
            "team_has_no_active_rotation",
            "Team has no enabled rotations",
            "Alerts routed to this team cannot resolve a rotation assignee unless routes use another explicit target.",
            hint="Create and enable at least one rotation for this team.",
        ))

    if enabled_routes and not enabled_channels:
        issues.append(issue_for_team(
            team,
            "warning",
            "team_has_no_enabled_channels",
            "Team has no enabled notification channels",
            "Enabled routes can receive alerts, but no team notification channels are enabled.",
            hint="Enable at least one channel or intentionally rely on profile-level notifications.",
        ))

    for route in enabled_routes:
        route_rotation_id = getattr(route, "rotation_id", None)
        if not route_rotation_id:
            route_rotation = getattr(route, "rotation", None)
            route_rotation_id = getattr(route_rotation, "id", None)

        route_policy_id = getattr(route, "escalation_policy_id", None)
        if not route_policy_id:
            route_policy = getattr(route, "escalation_policy", None)
            route_policy_id = getattr(route_policy, "id", None)

        if not route_rotation_id and not route_policy_id:
            issues.append(issue_for_team(
                team,
                "warning",
                "route_has_no_assignment_target",
                "Enabled route has no assignment target",
                (
                    f"Route '{route.name}' can receive alerts but has neither "
                    "a rotation nor an escalation policy assigned."
                ),
                hint="Attach a rotation or an escalation policy that can resolve an assignee.",
            ))
        if route_channel_count(route) == 0:
            issues.append(issue_for_team(
                team,
                "warning",
                "route_has_no_channels",
                "Enabled route has no channel links",
                f"Route '{route.name}' has no linked channels.",
                target_type="route",
                target_id=route.id,
                hint="Link at least one channel to the route.",
            ))

    if include_rotation_issues:
        for rotation in rotations:
            issues.extend(collect_rotation_health_issues(
                rotation,
                start,
                end,
                include_schedule_gaps=include_schedule_gaps,
                sample_minutes=sample_minutes,
            ))

    return serialize_health_payload("team", team, issues, start, end)


def get_team_or_none(team_id: int):
    try:
        return teams_repo.get_team(team_id)
    except DoesNotExist:
        return None


def get_rotation_or_none(rotation_id: int):
    try:
        return rotations_repo.get_rotation(rotation_id)
    except DoesNotExist:
        return None
