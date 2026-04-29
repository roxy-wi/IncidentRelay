#!/usr/bin/env python3
import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_database
from app.modules.db.migrations import MigrationError, create_migration, list_migrations, migrate, rollback


def main():
    """
    Run the RMON-like database migration CLI.
    """

    db = init_database()
    db.connect(reuse_if_open=True)

    parser = argparse.ArgumentParser(description="On-call database migration tool")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    create_parser = subparsers.add_parser("create", help="Create a new migration")
    create_parser.add_argument("name", help="Migration name")

    migrate_parser = subparsers.add_parser("migrate", help="Apply pending migrations")
    migrate_parser.add_argument("--up-to", help="Migrate up to a specific migration")

    rollback_parser = subparsers.add_parser("rollback", help="Rollback migrations")
    rollback_parser.add_argument("--count", type=int, default=1, help="Number of migrations to rollback")

    subparsers.add_parser("list", help="List migration status")

    args = parser.parse_args()

    try:
        if args.command == "create":
            print(f"Created migration file: {create_migration(args.name)}")
        elif args.command == "migrate":
            migrate(args.up_to)
        elif args.command == "rollback":
            rollback(args.count)
        elif args.command == "list":
            list_migrations()
        else:
            parser.print_help()
    except MigrationError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    finally:
        if not db.is_closed():
            db.close()


if __name__ == "__main__":
    main()
