from flask import Blueprint, jsonify, request

from app.modules.db import audit_repo
from app.modules.db.models import ApiToken, Group, Team, User
from app.services.rbac import (
    get_audit_log_group_ids,
    parse_date_or_datetime,
    require_audit_log_access,
)


audit_logs_bp = Blueprint("audit_logs_api", __name__)


def _serialize_actor(user):
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


def _serialize_group(group):
    if not group:
        return None
    return {
        "id": group.id,
        "name": group.name,
        "slug": group.slug,
    }


def _serialize_team(team):
    if not team:
        return None
    return {
        "id": team.id,
        "name": team.name,
        "slug": team.slug,
        "group_id": team.group_id,
    }


def _serialize_api_token(token):
    if not token:
        return None
    return {
        "id": token.id,
        "name": token.name,
        "token_prefix": token.token_prefix,
    }


def _load_map(model, ids):
    normalized_ids = sorted({int(item_id) for item_id in ids if item_id})
    if not normalized_ids:
        return {}
    return {
        item.id: item
        for item in model.select().where(model.id.in_(normalized_ids))
    }


def _serialize_entries(entries):
    groups = _load_map(Group, [entry.group_id for entry in entries])
    teams = _load_map(Team, [entry.team_id for entry in entries])
    users = _load_map(User, [entry.user_id for entry in entries])
    tokens = _load_map(ApiToken, [entry.api_token_id for entry in entries])

    payload = []
    for entry in entries:
        team = teams.get(entry.team_id)
        group = groups.get(entry.group_id)
        if group is None and team and team.group_id:
            group = groups.get(team.group_id)
            if group is None:
                group = Group.get_or_none(Group.id == team.group_id)

        payload.append({
            "id": entry.id,
            "action": entry.action,
            "object_type": entry.object_type,
            "object_id": entry.object_id,
            "message": entry.message,
            "data": entry.data or {},
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "group": _serialize_group(group),
            "team": _serialize_team(team),
            "actor": _serialize_actor(users.get(entry.user_id)),
            "api_token": _serialize_api_token(tokens.get(entry.api_token_id)),
        })

    return payload


def _scope_groups(group_ids):
    query = Group.select().order_by(Group.name.asc(), Group.id.asc())
    if group_ids is not None:
        if not group_ids:
            return []
        query = query.where(Group.id.in_(group_ids))
    return [
        {
            "id": group.id,
            "name": group.name,
            "slug": group.slug,
            "active": bool(group.active),
            "deleted": bool(group.deleted),
        }
        for group in query
    ]


def _filter_users(actor_ids):
    if not actor_ids:
        return []
    return [
        _serialize_actor(user)
        for user in (
            User
            .select()
            .where(User.id.in_(actor_ids))
            .order_by(User.display_name.asc(), User.username.asc())
        )
    ]


@audit_logs_bp.route("", methods=["GET"])
def list_audit_logs():
    """Return audit entries visible to the current administrator/editor."""

    access_error = require_audit_log_access()
    if access_error:
        return access_error

    group_ids = get_audit_log_group_ids()
    requested_group_id = request.args.get("group_id", type=int)

    if requested_group_id and group_ids is not None and requested_group_id not in group_ids:
        return jsonify({
            "error": "audit_log_group_access_denied",
            "message": "Access to this group audit log is denied",
        }), 403

    try:
        date_from = parse_date_or_datetime(request.args.get("date_from"))
        date_to = parse_date_or_datetime(request.args.get("date_to"))
    except ValueError:
        return jsonify({
            "error": "invalid_audit_log_date",
            "message": "Audit log dates must use ISO format",
        }), 400

    base_query = audit_repo.scoped_audit_query(group_ids=group_ids)
    filtered_query = audit_repo.filter_audit_query(
        base_query,
        search=request.args.get("search") or request.args.get("q"),
        group_id=requested_group_id,
        actor_id=request.args.get("actor_id", type=int),
        action=request.args.get("action"),
        object_type=request.args.get("object_type"),
        date_from=date_from,
        date_to=date_to,
    )

    page = audit_repo.paginate_audit_query(
        filtered_query,
        page=request.args.get("page", 1, type=int),
        page_size=request.args.get("page_size", 25, type=int),
    )
    options = audit_repo.audit_filter_options(base_query)
    groups = _scope_groups(group_ids)
    summary = audit_repo.audit_summary(filtered_query)
    summary["groups"] = len(groups)

    return jsonify({
        "items": _serialize_entries(page["items"]),
        "pagination": page["pagination"],
        "summary": summary,
        "filters": {
            "groups": groups,
            "actors": _filter_users(options["actor_ids"]),
            "actions": options["actions"],
            "object_types": options["object_types"],
        },
        "permissions": {
            "is_global_admin": group_ids is None,
            "group_ids": None if group_ids is None else group_ids,
        },
    })
