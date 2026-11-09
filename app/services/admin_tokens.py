"""Recheck personal token authority inside administrative transactions."""

from app.modules.common import utc_now
from app.modules.db.models import ApiToken
from app.modules.db.transactions import lock_row
from app.services.api_token_scopes import token_has_scopes
from app.services.rbac import current_api_token


def lock_admin_api_token(actor_id, scope, *, group_id=None):
    """Lock a request token until commit; JWT and internal callers need no token.

    Administrative resources span teams, so team-bound credentials cannot
    manage them. Group-bound tokens may only manage that Group's resources;
    installation-wide settings and central integrations require no Group bound.
    """
    authenticated = current_api_token()
    if authenticated is None:
        return
    token = lock_row(ApiToken.select().where(ApiToken.id == authenticated.id))
    if (
        token is None
        or not token.active
        or token.deleted
        or token.change_integration_id is not None
        or token.user_id != actor_id
        or token.team_id is not None
        or (token.group_id is not None and token.group_id != group_id)
        or (token.expires_at is not None and token.expires_at <= utc_now())
        or not token_has_scopes(token.scopes, [scope])
    ):
        raise PermissionError("Administrative API token access denied")
