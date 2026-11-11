"""Imported schedule reads and enforcement of source-owned resource policies."""

from datetime import timedelta

from flask import jsonify, request

from app.modules.common import as_utc_naive, utc_now
from app.modules.db.models import (
    DirectorySyncBinding as Binding, DirectorySyncCurrent as Current,
    DirectorySyncShift as Shift, DirectorySyncSource as Source,
    Rotation, RotationLayer, RotationLayerMember, RotationMember, RotationOverride,
    TeamUser, User, UserGroup,
)
from app.modules.user_colors import user_color
from app.services.directory_sync.fetch import instant
from app.services.directory_sync.reconcile import shared_user
from app.services.rbac import can_manage_group_users, can_read_team


def source_for(kind, local_id):
    """Only an owned, present binding changes local behavior."""
    binding = Binding.select(Binding, Source).join(Source).where(
        Binding.kind == kind, Binding.local_id == local_id,
        Binding.owned == True, Binding.present == True,
    ).first()
    return binding.source if binding else None


def import_metadata(kind, local_id):
    source = source_for(kind, local_id)
    if not source:
        return None
    result = {"source_id": source.id, "source_name": source.name,
              "editable": source.config.get("editable", False)}
    if kind == "rotation" and "current" in source.config.get("operations", {}):
        current = Current.get_or_none(Current.rotation == local_id)
        result["current_status"] = current.status if current and current.valid_until > utc_now() else "stale"
        result["current_valid_until"] = current.valid_until.isoformat() + "Z" if current else None
    return result


def sync_managed_groups(user_id):
    """Scope API membership authority to imported users and destination groups."""
    membership_ids = UserGroup.select(UserGroup.id).where(UserGroup.user == user_id)
    return {source.group_id for source in Source.select().join(Binding).where(
        Binding.kind == "group_member", Binding.local_id.in_(membership_ids),
        Binding.present == True, Binding.owned == True,
    ) if source.config.get("membership_authority", "sync") == "sync"}


def readonly(kind, local_id):
    source = source_for(kind, local_id)
    if not source or source.config.get("editable", False):
        return False
    if kind == "user" and shared_user(local_id, source.group_id):
        return False
    return True


def sync_managed_team_member(user_id, team_id):
    """Keep API-owned team roles independent of unrelated OIDC group mappings."""
    membership = TeamUser.get_or_none(TeamUser.user == user_id, TeamUser.team == team_id)
    source = source_for("team_member", membership.id) if membership else None
    return bool(source and source.config.get("membership_authority", "sync") == "sync")


def guard_mutation():
    """Protect imported entities on their existing API endpoints, including children."""
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    args = request.view_args or {}
    kind, local_id = None, None
    blueprint = request.blueprint
    actor = getattr(request, "current_user", None)
    if not actor:
        return None
    if blueprint == "teams_api":
        kind, local_id = "team", args.get("team_id")
        if not local_id and args.get("membership_id"):
            row = TeamUser.get_or_none(TeamUser.id == args["membership_id"])
            local_id = row.team_id if row else None
    elif blueprint == "rotations_api":
        kind, local_id = "rotation", args.get("rotation_id")
        if args.get("shift_id"):
            shift = Shift.get_or_none(Shift.id == args["shift_id"])
            local_id = shift.rotation_id if shift else None
        if not local_id:
            children = (("override_id", RotationOverride), ("layer_id", RotationLayer),
                        ("member_id", RotationLayerMember if "/layers/members/" in request.path else RotationMember))
            for key, model in children:
                if args.get(key):
                    row = model.get_or_none(model.id == args[key])
                    if row:
                        local_id = row.layer.rotation_id if model is RotationLayerMember else row.rotation_id
                    break
    elif blueprint in {"users_api", "admin_users_api"}:
        if not actor.is_admin:
            return None  # Let the endpoint return its normal authorization error.
        kind, local_id = "user", args.get("user_id")
    elif blueprint == "profile_api" and request.method == "PUT" and request.endpoint == "profile_api.update_profile":
        payload = request.get_json(silent=True)
        if isinstance(payload, dict) and any(
            key in payload and payload[key] != getattr(actor, key)
            for key in ("email", "display_name", "phone")
        ):
            kind, local_id = "user", actor.id
    elif blueprint == "groups_api":
        membership = None
        if args.get("membership_id"):
            membership = UserGroup.get_or_none(UserGroup.id == args["membership_id"])
        elif request.endpoint == "groups_api.add_group_user":
            payload = request.get_json(silent=True)
            if isinstance(payload, dict):
                try:
                    user_id = int(payload.get("user_id"))
                except (TypeError, ValueError, OverflowError):
                    return None  # The endpoint validates malformed input normally.
                membership = UserGroup.get_or_none(UserGroup.group == args["group_id"], UserGroup.user == user_id)
        if membership:
            if not can_manage_group_users(actor, membership.group_id):
                return None
            kind, local_id = "group_member", membership.id
    if kind in {"team", "rotation"} and local_id:
        rotation = Rotation.get_or_none(Rotation.id == local_id) if kind == "rotation" else None
        team_id = rotation.team_id if rotation else local_id if kind == "team" else None
        if not team_id or not can_read_team(actor, team_id):
            return None
    if kind and local_id and readonly(kind, local_id):
        return jsonify(error="sync_readonly", message="This resource is read-only; change the synchronization source settings to edit it"), 409
    return None


def current_user(rotation, source, at):
    """Return no assignee for stale, missing, unavailable or ambiguous current state."""
    at = as_utc_naive(at)
    if source.config.get("editable") and Shift.select().where(
        Shift.rotation == rotation.id, Shift.local_override == True,
        ((Shift.local_from <= at) & (Shift.local_until > at))
        | ((Shift.starts_at <= at) & (Shift.ends_at > at)),
    ).exists():
        return scheduled_user(rotation, at)
    if "current" in source.config.get("operations", {}):
        cached = Current.get_or_none(Current.rotation == rotation.id)
        if (not cached or cached.status != "active" or cached.observed_at > at + timedelta(seconds=1)
                or cached.valid_until <= at or cached.valid_until <= utc_now()):
            return None
        user = cached.user if cached.user_id else None
        return user if user and user.active and not user.deleted else None
    return scheduled_user(rotation, at)


def scheduled_user(rotation, at):
    events = imported_candidates(rotation, at, at + timedelta(microseconds=1))
    if not events or events[0]["event"].get("unavailable"):
        return None
    return User.get_or_none(User.id == events[0]["event"]["user_id"], User.active == True, User.deleted == False)


def imported_candidates(rotation, start, end):
    """Split concrete shifts at replacement boundaries; overlaps remain unassigned."""
    start, end = as_utc_naive(start), as_utc_naive(end)
    rows = list(Shift.select().where(Shift.rotation == rotation.id, Shift.deleted == False,
                                     Shift.starts_at < end, Shift.ends_at > start))
    user_ids = {row.user_id for row in rows}
    user_ids.update(item["user_id"] for row in rows for item in row.replacements)
    users = {user.id: user for user in User.select().where(User.id.in_(user_ids))}
    points = {start, end}
    for row in rows:
        points.update((max(start, row.starts_at), min(end, row.ends_at)))
        for replacement in row.replacements:
            points.update(value for value in (instant(replacement["start"]), instant(replacement["end"])) if start < value < end)
    points = sorted(points)
    events = []
    for left, right in zip(points, points[1:], strict=False):
        active = [row for row in rows if row.starts_at <= left and row.ends_at >= right]
        if len(active) != 1:
            continue
        row = active[0]
        replacements = [item for item in row.replacements if instant(item["start"]) <= left and instant(item["end"]) >= right]
        replacement = max(replacements, key=lambda item: item["precedence"]) if replacements else None
        if replacement and len({item["user_id"] for item in replacements
                                if item["precedence"] == replacement["precedence"]}) > 1:
            continue
        user_id = replacement["user_id"] if replacement else row.user_id
        user = users.get(user_id)
        if not user or user.deleted:
            continue
        unavailable = (replacement.get("inactive", False) if replacement else row.unavailable) or not user.active
        events.append({"_start": left, "_end": right, "_priority": -1000000, "_order": row.id,
                       "event": {"rotation_id": rotation.id, "rotation_name": rotation.name,
                                 "team_id": rotation.team_id, "team_name": rotation.team.name,
                                 "team_slug": rotation.team.slug, "timezone": rotation.timezone,
                                 "user_id": user.id, "username": user.username, "display_name": user.display_name,
                                 "color": user_color(user), "type": "imported", "layer_id": None,
                                 "layer_name": row.title, "unavailable": unavailable,
                                 "external_shift_id": row.external_id}})
    return events


def next_scheduled_user(rotation, at, current=None):
    """Use future concrete assignments instead of inventing a cyclic member order."""
    for candidate in imported_candidates(rotation, at, at + timedelta(days=366)):
        event = candidate["event"]
        if not event["unavailable"] and (current is None or event["user_id"] != current.id):
            user = User.get_by_id(event["user_id"])
            if user.active and not user.deleted:
                return user
    return None
