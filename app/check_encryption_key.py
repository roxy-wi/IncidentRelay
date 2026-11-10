"""Check or safely initialize the database verifier before starting workers."""

import sys

from app.services.encryption_keys import (
    EncryptionKeyVerificationError,
    verify_encryption_key,
)


def main():
    """Use exactly the application's effective config and never print secrets."""
    try:
        verify_encryption_key()
    except EncryptionKeyVerificationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Database encryption key verification succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
