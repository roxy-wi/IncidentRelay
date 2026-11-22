"""Token digests shared by storage and authentication without HTTP dependencies."""

import hashlib


def hash_token(raw_token):
    """Return the SHA-256 digest used for persisted token lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
