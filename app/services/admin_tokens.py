"""Recheck personal token authority inside administrative transactions."""

from app.modules.db.models import ApiToken
from app.modules.db.transactions import lock_row
from app.services.api_token_scopes import token_has_scopes
from app.services.rbac import current_api_token
from app.services.authorization import token_allows_owner, valid_personal_token


def lock_admin_api_token(actor_id, scope, *, group_id=None, for_update=True):
    """Lock a request token until commit; JWT and internal callers need no token.

    Administrative resources span teams, so team-bound credentials cannot
    manage them. Group-bound tokens may only manage that Group's resources;
    installation-wide settings and central integrations require no Group bound.
    Read-only endpoints may set for_update=False to validate without a write lock.
    """
    authenticated = current_api_token()
    if authenticated is None:
        return
    query = ApiToken.select().where(ApiToken.id == authenticated.id)
    token = lock_row(query) if for_update else query.first()
    if (
        not valid_personal_token(token)
        or token.user_id != actor_id
        or not token_allows_owner(group_id, token=token)
        or not token_has_scopes(token.scopes, [scope])
    ):
        raise PermissionError("Administrative API token access denied")
