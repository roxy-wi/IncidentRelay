from datetime import datetime, timedelta

import jwt
from werkzeug.security import check_password_hash, generate_password_hash

from app.settings import Config


JWT_ALGORITHM = "HS256"


def hash_password(password):
    """
    Return a secure password hash.
    """

    return generate_password_hash(password)


def verify_password(password, password_hash):
    """
    Verify a password against a stored hash.
    """

    if not password_hash:
        return False

    return check_password_hash(password_hash, password)


def create_access_token(user):
    """
    Create a JWT access token for a user.
    """

    expires_at = datetime.utcnow() + timedelta(minutes=Config.JWT_EXPIRE_MINUTES)

    payload = {
        "sub": str(user.id),
        "username": user.username,
        "is_admin": bool(user.is_admin),
        "exp": expires_at,
        "iat": datetime.utcnow(),
    }

    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    return token, expires_at


def decode_access_token(token):
    """
    Decode and validate a JWT access token.
    """

    return jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
