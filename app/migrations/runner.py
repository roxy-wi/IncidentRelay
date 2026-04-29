from app.modules.db.migrations import list_migrations, migrate
from app.version import get_service_version


def migration_status():
    """
    Return migration status for API and CLI consumers.
    """

    return {
        "service_version": get_service_version(),
        "migrations": list_migrations(),
    }
