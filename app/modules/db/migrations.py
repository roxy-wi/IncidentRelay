import importlib.util
import os
import re
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from app.db import init_database
from app.modules.db.models import Migration


class MigrationError(Exception):
    """
    Exception raised for migration errors.
    """


def get_migrations_dir() -> str:
    """
    Return the application migrations directory.
    """

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    migrations_dir = os.path.join(base_dir, "migrations")

    if not os.path.exists(migrations_dir):
        os.makedirs(migrations_dir)

    return migrations_dir


def get_migration_files() -> List[str]:
    """
    Return real migration filenames sorted by name.

    Only files with names like 20260427000001_initial_schema.py are
    considered migrations. Helper modules such as runner.py and __init__.py
    must never be loaded as migration files.
    """

    migration_name_re = re.compile(r"^\d{14}_[a-z0-9_]+\.py$")

    return sorted(
        filename
        for filename in os.listdir(get_migrations_dir())
        if migration_name_re.match(filename)
    )


def ensure_migration_table():
    """
    Ensure the migration table exists.
    """

    db = init_database()
    db.create_tables([Migration], safe=True)


def get_applied_migrations() -> List[str]:
    """
    Return applied migration names.
    """

    ensure_migration_table()
    return [item.name for item in Migration.select().order_by(Migration.id.asc())]


def create_migration(name: str) -> str:
    """
    Create a migration file from a template.
    """

    if not re.match(r"^[a-z0-9_]+$", name):
        raise MigrationError("Migration name must contain only lowercase letters, numbers, and underscores")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{name}.py"
    filepath = os.path.join(get_migrations_dir(), filename)

    if os.path.exists(filepath):
        raise MigrationError(f"Migration file {filename} already exists")

    template = '''from peewee import *
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.migrator import get_migrator


db = init_database()
migrator = get_migrator(db)


def upgrade():
    """
    Apply migration changes.
    """

    pass


def downgrade():
    """
    Roll back migration changes.
    """

    pass
'''

    with open(filepath, "w", encoding="utf-8") as migration_file:
        migration_file.write(template)

    return filepath


def load_migration_module(filepath: str) -> Tuple[Callable, Optional[Callable]]:
    """
    Load a migration module from a file.
    """

    module_name = os.path.basename(filepath).replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "upgrade"):
        raise MigrationError(f"Migration {module_name} does not have an upgrade function")

    return module.upgrade, getattr(module, "downgrade", None)


def apply_migration(filepath: str) -> None:
    """
    Apply a single migration file.
    """

    ensure_migration_table()
    filename = os.path.basename(filepath)
    migration_name = filename.replace(".py", "")

    if Migration.select().where(Migration.name == migration_name).exists():
        print(f"Migration {migration_name} has already been applied")
        return

    upgrade_func, _ = load_migration_module(filepath)

    try:
        print(f"Applying migration {migration_name}...")
        upgrade_func()
        Migration.create(name=migration_name)
        print(f"Migration {migration_name} applied successfully")
    except Exception as exc:
        raise MigrationError(f"Failed to apply migration {migration_name}: {exc}") from exc


def rollback_migration(migration_name: str) -> None:
    """
    Roll back a single migration by name.
    """

    ensure_migration_table()
    migration_record = Migration.get_or_none(Migration.name == migration_name)

    if not migration_record:
        raise MigrationError(f"Migration {migration_name} has not been applied")

    filepath = os.path.join(get_migrations_dir(), f"{migration_name}.py")

    if not os.path.exists(filepath):
        raise MigrationError(f"Migration file {migration_name}.py not found")

    _, downgrade_func = load_migration_module(filepath)

    if downgrade_func is None:
        raise MigrationError(f"Migration {migration_name} does not have a downgrade function")

    try:
        print(f"Rolling back migration {migration_name}...")
        downgrade_func()
        migration_record.delete_instance()
        print(f"Migration {migration_name} rolled back successfully")
    except Exception as exc:
        raise MigrationError(f"Failed to rollback migration {migration_name}: {exc}") from exc


def migrate(up_to: Optional[str] = None) -> None:
    """
    Apply all pending migrations or stop at a selected migration.
    """

    migration_files = get_migration_files()
    applied_migrations = set(get_applied_migrations())
    pending_migrations = []

    for filename in migration_files:
        migration_name = filename.replace(".py", "")

        if migration_name not in applied_migrations:
            pending_migrations.append(filename)

        if up_to and migration_name == up_to:
            break

    if not pending_migrations:
        print("No pending migrations to apply")
        return

    for filename in pending_migrations:
        apply_migration(os.path.join(get_migrations_dir(), filename))


def rollback(count: int = 1) -> None:
    """
    Roll back the last applied migrations.
    """

    applied_migrations = list(reversed(get_applied_migrations()))

    if not applied_migrations:
        print("No migrations to rollback")
        return

    for migration_name in applied_migrations[:count]:
        rollback_migration(migration_name)


def list_migrations() -> List[dict]:
    """
    Return migration statuses and print them for CLI usage.
    """

    migration_files = get_migration_files()
    applied_migrations = set(get_applied_migrations())
    result = []

    print("Migrations:")

    for filename in migration_files:
        migration_name = filename.replace(".py", "")
        status = "Applied" if migration_name in applied_migrations else "Pending"
        result.append({"name": migration_name, "status": status})
        print(f" {migration_name}: {status}")

    return result
