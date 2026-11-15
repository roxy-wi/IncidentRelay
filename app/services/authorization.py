"""Shared credential bounds and resource authorization.

Authentication adapters retain their wire protocols. This module intersects
their authority with existing RBAC, including when a resource is selected late
by routing or deduplication. It never infers ownership from request payloads.
"""

from dataclasses import dataclass

from flask import g, has_request_context, request

from app.modules.common import utc_now
from app.modules.db.models import AlertRoute, ApiToken, Service, Team
from app.modules.db.transactions import lock_row
from app.services.api_token_scopes import (
    is_public_api_request, required_scopes_for_path,
    token_can_grant_scopes, token_has_scopes,
)


class AccessDenied(PermissionError):
    """Reject an operation without disclosing the target or credential."""


@dataclass(frozen=True)
class AuthorizationContext:
    """Authenticated authority; request data cannot construct this context."""

    kind: str
    user: object = None
    token: object = None
    route: object = None


def bind_authorization(*, kind, user=None, token=None, route=None):
    """Install one authority and clear unrelated legacy request identities."""
    context = AuthorizationContext(kind, user, token, route)
    g.authorization = context
    request.current_user = user
    request.current_api_token = token
    request.current_intake_route = route
    request.current_auth_type = kind
    return context


def current_authorization():
    """Read the common context, accepting existing internal request adapters."""
    if not has_request_context():
        return AuthorizationContext("internal")
    context = getattr(g, "authorization", None)
    if context is not None:
        return context
    token = getattr(request, "current_api_token", None)
    if token is None:
        token = getattr(g, "caldav_api_token", None)
    user = getattr(request, "current_user", None) or getattr(g, "caldav_user", None)
    route = getattr(request, "current_intake_route", None)
    kind = getattr(request, "current_auth_type", None)
    return AuthorizationContext(
        kind or ("api_token" if token else "route_token" if route else
                 "jwt" if user else "anonymous"), user, token, route,
    )


def valid_personal_token(token):
    """Validate personal or explicitly bounded legacy integration credentials."""
    if (
        token is None or not token.active or token.deleted
        or token.change_integration_id is not None
        or (token.expires_at is not None and token.expires_at <= utc_now())
    ):
        return False
    if token.user_id is None:
        return token.group_id is not None or token.team_id is not None
    user = token.user
    return bool(user and user.active and not user.deleted)


def token_allows_operation(token, required_scopes):
    """Use one scope gate for middleware and protocol-specific adapters."""
    return bool(
        required_scopes is not None and valid_personal_token(token)
        and token_has_scopes(token.scopes or [], required_scopes)
    )


def token_allows_owner(group_id=None, team_id=None, *, token=None):
    """Check stored ownership, including global resources and admin tokens."""
    token = token if token is not None else current_authorization().token
    if token is None:
        return True
    if not valid_personal_token(token):
        return False
    return (
        (token.group_id is None or token.group_id == group_id)
        and (token.team_id is None or token.team_id == team_id)
    )


def token_allows_team(team_id, *, token=None):
    """Resolve the current parent Group instead of trusting a supplied ID."""
    token = token if token is not None else current_authorization().token
    if token is None:
        return True
    if team_id is None:
        return token_allows_owner(token=token)
    team = Team.get_or_none(Team.id == team_id)
    return bool(team and token_allows_owner(team.group_id, team.id, token=token))


def token_allows_group(group_id, *, team_resource=False, token=None):
    """Optionally allow reading the parent Group of a team-bound token."""
    token = token if token is not None else current_authorization().token
    if token is None:
        return True
    team_id = None
    if team_resource and token.team_id is not None:
        team = Team.get_or_none(Team.id == token.team_id)
        if team is None or team.group_id != group_id:
            return False
        team_id = team.id
    return token_allows_owner(group_id, team_id, token=token)


def filter_group_ids(group_ids):
    """Intersect collection visibility with credential bounds."""
    token = current_authorization().token
    if token is None:
        return group_ids
    if not valid_personal_token(token):
        return []
    allowed = set(group_ids)
    if token.group_id is not None:
        allowed.intersection_update({token.group_id})
    if token.team_id is not None:
        team = Team.get_or_none(Team.id == token.team_id)
        allowed.intersection_update({team.group_id} if team else set())
    return [value for value in group_ids if value in allowed]


def filter_team_ids(team_ids):
    """Apply bounds with one ownership query, without per-team lookups."""
    token = current_authorization().token
    if token is None:
        return team_ids
    if not valid_personal_token(token):
        return []
    query = Team.select(Team.id).where(Team.id.in_(team_ids))
    if token.group_id is not None:
        query = query.where(Team.group == token.group_id)
    if token.team_id is not None:
        query = query.where(Team.id == token.team_id)
    allowed = {team.id for team in query}
    return [value for value in team_ids if value in allowed]


def authorize_team(user, team_id, permission):
    """Combine token bounds with the existing, user-only RBAC rules."""
    from app.services import rbac

    checks = {
        "read": rbac._user_can_read_team,
        "write": rbac._user_can_write_team,
        "respond": rbac._user_can_respond_team,
        "oncall": rbac._user_can_view_team_oncall,
        "manage_users": rbac._user_can_manage_team_users,
        "resource_read": lambda u, t: rbac._user_can_access_team_or_group_resource(u, t),
        "resource_write": lambda u, t: rbac._user_can_access_team_or_group_resource(
            u, t, write_required=True,
        ),
    }
    check = checks.get(permission)
    return bool(check and token_allows_team(team_id) and check(user, team_id))


def authorize_group(user, group_id, permission):
    """Apply Group permissions without letting team tokens edit the Group."""
    from app.services import rbac

    checks = {
        "read": rbac._user_can_read_group,
        "write": rbac._user_can_write_group,
        "manage_users": rbac._user_can_manage_group_users,
    }
    check = checks.get(permission)
    return bool(
        check and token_allows_group(group_id, team_resource=permission == "read")
        and check(user, group_id)
    )


def unrestricted_admin(user=None):
    """A global-admin owner cannot remove the bounds of their credential."""
    context = current_authorization()
    user = user or context.user
    return bool(user and user.is_admin and token_allows_owner())


def delegated_token_bounds(group_id, scopes, expires_at):
    """Inherit or narrow every authority dimension when issuing a token."""
    parent = current_authorization().token
    if parent is None:
        return group_id, None, expires_at
    if not valid_personal_token(parent) or not token_can_grant_scopes(parent.scopes, scopes):
        raise AccessDenied("Token delegation denied")
    group_id = group_id if group_id is not None else parent.group_id
    if parent.team_id is not None:
        team = Team.get_or_none(Team.id == parent.team_id)
        if team is None or (group_id is not None and group_id != team.group_id):
            raise AccessDenied("Token delegation denied")
        group_id = group_id if group_id is not None else team.group_id
    if not token_allows_owner(group_id, parent.team_id, token=parent):
        raise AccessDenied("Token delegation denied")
    if parent.expires_at is not None:
        expires_at = min(expires_at, parent.expires_at) if expires_at else parent.expires_at
    return group_id, parent.team_id, expires_at


def require_intake_group(group_id, *, source=None):
    """Check orchestration's Group before evaluating or persisting its rules."""
    context = current_authorization()
    if context.kind == "internal":
        return
    if context.route is not None:
        if context.route.team.group_id == group_id:
            return
    elif context.token is not None:
        from app.services import rbac

        if (
            token_has_scopes(context.token.scopes, [
                "heartbeats:write" if source == "heartbeat" else "alerts:write",
            ])
            and token_allows_group(group_id, team_resource=True)
            and (context.user is None or rbac._user_can_read_group(context.user, group_id))
        ):
            return
    elif context.kind == "jwt":
        from app.services import rbac
        if rbac._user_can_read_group(context.user, group_id):
            return
    raise AccessDenied("Alert intake access denied")


def require_intake_team(team_id, *, source=None):
    """Authorize a Team hint before orchestration has chosen a route."""
    context = current_authorization()
    if context.kind == "internal":
        return
    team = Team.get_or_none(Team.id == team_id)
    if team is None:
        raise AccessDenied("Alert intake access denied")
    require_intake_group(team.group_id, source=source)
    if context.route is not None:
        if team.id == context.route.team_id:
            return
    elif token_allows_team(team.id):
        from app.services import rbac
        if context.user is None or (
            rbac._user_can_respond_team(context.user, team.id)
            or rbac._user_can_write_team(context.user, team.id)
        ):
            return
    raise AccessDenied("Alert intake access denied")


def require_intake_route(route, *, service=None, lock=False):
    """Authorize the actual route, including routes selected by orchestration."""
    context = current_authorization()
    if route is None:
        if context.kind == "internal":
            return
        raise AccessDenied("Alert intake access denied")
    query = AlertRoute.select().where(AlertRoute.id == route.id)
    stored_route = lock_row(query) if lock else query.get_or_none()
    if stored_route is None or stored_route.team_id != route.team_id:
        raise AccessDenied("Alert intake access denied")
    if lock:
        # Keep parent ownership stable until the mutation commits.
        lock_row(Team.select().where(Team.id == stored_route.team_id))
    if service is not None:
        query = Service.select().where(Service.id == service.id)
        stored_service = lock_row(query) if lock else query.get_or_none()
        if (
            stored_service is None
            or stored_service.team_id != route.team_id
        ):
            raise AccessDenied("Alert intake access denied")
    if context.kind == "internal":
        return
    if context.route is not None:
        if route.id == context.route.id and route.team_id == context.route.team_id:
            return
    elif context.token is not None:
        from app.services import rbac

        if (
            token_has_scopes(context.token.scopes, [
                "heartbeats:write" if route.source == "heartbeat" else "alerts:write",
            ])
            and token_allows_team(route.team_id)
            and (
                context.user is None
                or rbac._user_can_respond_team(context.user, route.team_id)
                or rbac._user_can_write_team(context.user, route.team_id)
            )
        ):
            return
    elif context.kind == "jwt":
        from app.services import rbac
        if rbac._user_can_write_team(context.user, route.team_id):
            return
    raise AccessDenied("Alert intake access denied")


def require_intake_target(target, route):
    """Do not let a scoped child lookup mutate a differently owned group."""
    require_intake_route(route)
    if target.route_id != route.id or target.team_id != route.team_id:
        raise AccessDenied("Alert intake access denied")


def refresh_authority(*, lock=False):
    """Recheck credential state inside sensitive write transactions."""
    context = current_authorization()
    if context.route is not None:
        query = AlertRoute.select().where(AlertRoute.id == context.route.id)
        if lock:
            route = lock_row(query)
        else:
            route = query.get_or_none()
        from app.services.routing.routing import is_route_active
        if not is_route_active(route) or (
            context.kind == "route_token"
            and route.intake_token_hash != context.route.intake_token_hash
        ):
            raise AccessDenied("Alert intake access denied")
        return bind_authorization(kind=context.kind, route=route)
    if context.token is None or context.kind == "change_integration":
        return context
    query = ApiToken.select().where(ApiToken.id == context.token.id)
    if lock:
        token = lock_row(query)
    else:
        token = query.get_or_none()
    if not valid_personal_token(token) or token.user_id != context.token.user_id:
        raise AccessDenied("Token access denied")
    if context.kind == "caldav":
        required_scopes = ["calendar:read"]
    elif request.path.startswith("/api/") and not is_public_api_request(
        request.path, request.method,
    ):
        required_scopes = required_scopes_for_path(request.path, request.method)
    else:
        required_scopes = []  # Intake checks its capability at the final route.
    if not token_allows_operation(token, required_scopes):
        raise AccessDenied("Token access denied")
    return bind_authorization(kind=context.kind, user=token.user, token=token)


def recheck_team_write(team_id, *, destination_team_id=None, destination_group_id=None):
    """Recheck a personal token under the catalog mutation transaction."""
    if current_authorization().token is None:
        return
    context = refresh_authority(lock=True)
    if not authorize_team(context.user, team_id, "write"):
        raise AccessDenied("Team access denied")
    if destination_team_id is not None and not authorize_team(
        context.user, destination_team_id, "write",
    ):
        raise AccessDenied("Team access denied")
    if destination_group_id is not None and not token_allows_owner(
        destination_group_id, team_id,
    ):
        raise AccessDenied("Team access denied")
