"""Create an uninitialized verifier without trusting the migration process's key."""

from app.db import init_database
from app.modules.db.models import EncryptionKeyVerification


def upgrade():
    """Reserve the singleton used to serialize first startup across replicas."""
    with init_database().atomic():
        EncryptionKeyVerification.create_table(safe=True)
        EncryptionKeyVerification.insert(id=1).on_conflict_ignore().execute()


def downgrade():
    """Remove the verifier when explicitly rolling back this migration."""
    EncryptionKeyVerification.drop_table(safe=True)
