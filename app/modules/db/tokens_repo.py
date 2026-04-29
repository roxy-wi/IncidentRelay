from datetime import datetime

from app.modules.db.models import ApiToken


def create_api_token(name, token_prefix, token_hash, scopes, team_id=None, group_id=None, user_id=None, expires_at=None):
    """
    Create an API token.
    """

    return ApiToken.create(
        team=team_id,
        group=group_id,
        user=user_id,
        name=name,
        token_prefix=token_prefix,
        token_hash=token_hash,
        scopes=scopes or [],
        expires_at=expires_at,
    )


def list_api_tokens(include_deleted=False):
    """
    Return API token metadata.
    """

    query = ApiToken.select().order_by(ApiToken.id.desc())

    if not include_deleted:
        query = query.where(ApiToken.deleted == False)

    return list(query)


def get_active_token_by_hash(token_hash):
    """
    Return an active API token by hash.
    """

    return ApiToken.get_or_none(
        (ApiToken.token_hash == token_hash)
        & (ApiToken.active == True)
        & (ApiToken.deleted == False)
    )


def mark_token_used(token):
    """
    Update last token usage timestamp.
    """

    token.last_used_at = datetime.utcnow()
    token.save()
    return token


def soft_delete_token(token_id):
    """
    Soft-delete an API token.
    """

    token = ApiToken.get_by_id(token_id)
    token.active = False
    token.deleted = True
    token.deleted_at = datetime.utcnow()
    token.save()
    return token


def create_token(name, token_prefix, token_hash, scopes, team=None, group=None, user=None, expires_at=None):
    """
    Backward-compatible API token creation helper.

    Some views use create_token(), while older code used create_api_token().
    Both helpers now create the same ApiToken record.
    """

    return create_api_token(
        name=name,
        token_prefix=token_prefix,
        token_hash=token_hash,
        scopes=scopes,
        team_id=team,
        group_id=group,
        user_id=user,
        expires_at=expires_at,
    )
