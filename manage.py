import argparse
import json
from datetime import datetime, timedelta

from app.db import init_database
from app.login import hash_password
from app.models import UserGroup
from app.modules.db.migrations import create_migration, list_migrations, migrate, rollback
from app.modules.db import channels_repo, groups_repo, rotations_repo, routes_repo, teams_repo, tokens_repo, users_repo
from app.services.auth import create_raw_token, hash_token
from app.version import get_service_version


def cmd_migrate(args):
    """
    Run all pending migrations.
    """

    db = init_database()
    db.connect(reuse_if_open=True)
    migrate(args.up_to)
    db.close()
    print("Migrations completed.")


def cmd_migration_status(args):
    """
    Print migration status.
    """

    db = init_database()
    db.connect(reuse_if_open=True)
    print(json.dumps({"service_version": get_service_version(), "migrations": list_migrations()}, indent=2))
    db.close()


def cmd_version(args):
    """
    Print service version.
    """

    print(get_service_version())


def cmd_create_token(args):
    """
    Create an API token and print the raw token once.
    """

    db = init_database()
    db.connect(reuse_if_open=True)

    team = teams_repo.get_team_by_slug(args.team) if args.team else None
    raw_token = create_raw_token()

    token = tokens_repo.create_api_token(
        name=args.name,
        token_prefix=raw_token[:12],
        token_hash=hash_token(raw_token),
        scopes=args.scopes.split(",") if args.scopes else ["alerts:write"],
        team_id=team.id if team else None,
        expires_at=datetime.utcnow() + timedelta(days=args.days) if args.days else None,
    )

    print(json.dumps({
        "id": token.id,
        "name": token.name,
        "token": raw_token,
        "token_prefix": token.token_prefix,
        "scopes": token.scopes,
    }, indent=2))

    db.close()



def create_group_if_missing(slug, name, description=None):
    """
    Create a group if it does not exist.
    """

    from app.models import Group

    group, created = Group.get_or_create(
        slug=slug,
        defaults={
            "name": name,
            "description": description,
            "active": True,
        },
    )

    if not created and not group.active:
        group.active = True
        group.save()

    return group


def detach_user_from_groups(user):
    """
    Disable all group memberships and clear active_group for an admin user.
    """

    UserGroup.update(active=False).where(UserGroup.user == user.id).execute()
    user.active_group = None
    user.save()


def ensure_user_in_group(user, group, role="rw"):
    """
    Add a user to a group and set active_group when missing.
    """

    groups_repo.add_user_to_group(user.id, group.id, role=role)

    if not user.active_group_id:
        users_repo.set_active_group(user.id, group.id)


def ensure_route_token(route):
    """
    Ensure a route has an intake token and return the raw token if generated.
    """

    if route.intake_token_hash:
        return None

    raw_token = create_raw_token()
    routes_repo.set_route_intake_token(route.id, raw_token[:12], hash_token(raw_token))
    return raw_token


def cmd_demo_data(args):
    """
    Create demo groups, users, teams, rotations, channels and routes.

    Rules:
    - demo admin is not attached to any group;
    - regular demo users are attached to their groups;
    - regular demo users have active_group set;
    - group and team roles use only supported values: read_only or rw.
    """

    db = init_database()
    db.connect(reuse_if_open=True)
    migrate()

    admin = users_repo.create_user_if_missing(
        username="admin",
        display_name="Admin",
        email="admin@example.com",
        password_hash=hash_password("admin123"),
        is_admin=True,
        active=True,
    )
    admin.is_admin = True
    admin.active = True
    admin.save()
    detach_user_from_groups(admin)

    infra_group = create_group_if_missing(
        slug="infra",
        name="Infrastructure",
        description="Infrastructure access group",
    )

    db_group = create_group_if_missing(
        slug="database",
        name="Database",
        description="Database access group",
    )

    infra = teams_repo.create_team_if_missing(
        group_id=infra_group.id,
        slug="infra",
        name="Infrastructure",
        description="Infrastructure administrators",
        escalation_after_reminders=2,
    )

    if infra.group_id != infra_group.id:
        teams_repo.update_team(infra.id, {"group": infra_group.id})

    db_team = teams_repo.create_team_if_missing(
        group_id=db_group.id,
        slug="db",
        name="Database",
        description="Database administrators",
        escalation_after_reminders=2,
    )

    if db_team.group_id != db_group.id:
        teams_repo.update_team(db_team.id, {"group": db_group.id})

    users_by_name = {}

    for username in ["ivan", "petr", "sergey"]:
        user = users_repo.create_user_if_missing(
            username=username,
            display_name=username.title(),
            email=f"{username}@example.com",
            password_hash=hash_password("changeme123"),
            is_admin=False,
            active=True,
        )
        user.is_admin = False
        user.active = True
        user.save()
        ensure_user_in_group(user, infra_group, role="rw")
        teams_repo.add_user_to_team(infra.id, user.id, role="rw")
        users_by_name[username] = users_repo.get_user(user.id)

    for username in ["anna", "maria", "oleg"]:
        user = users_repo.create_user_if_missing(
            username=username,
            display_name=username.title(),
            email=f"{username}@example.com",
            password_hash=hash_password("changeme123"),
            is_admin=False,
            active=True,
        )
        user.is_admin = False
        user.active = True
        user.save()
        ensure_user_in_group(user, db_group, role="rw")
        teams_repo.add_user_to_team(db_team.id, user.id, role="rw")
        users_by_name[username] = users_repo.get_user(user.id)

    now = datetime.utcnow().replace(microsecond=0)

    infra_rotation = rotations_repo.create_rotation_if_missing(
        team_id=infra.id,
        name="infra-primary",
        description="Primary infrastructure rotation",
        start_at=now,
        duration_seconds=86400,
        rotation_type="daily",
        interval_value=1,
        interval_unit="days",
        handoff_time="09:00",
    )

    db_rotation = rotations_repo.create_rotation_if_missing(
        team_id=db_team.id,
        name="db-primary",
        description="Primary database rotation",
        start_at=now,
        duration_seconds=86400,
        rotation_type="daily",
        interval_value=1,
        interval_unit="days",
        handoff_time="09:00",
    )

    for position, username in enumerate(["ivan", "petr", "sergey"]):
        rotations_repo.add_rotation_member(infra_rotation.id, users_by_name[username].id, position)

    for position, username in enumerate(["anna", "maria", "oleg"]):
        rotations_repo.add_rotation_member(db_rotation.id, users_by_name[username].id, position)

    infra_channel = channels_repo.create_channel_if_missing(
        team_id=infra.id,
        name="infra-webhook",
        channel_type="webhook",
        config={"webhook_url": "https://example.com/infra"},
    )

    if infra_channel.group_id != infra_group.id:
        channels_repo.update_channel(infra_channel.id, {"group": infra_group.id})

    db_channel = channels_repo.create_channel_if_missing(
        team_id=db_team.id,
        name="db-webhook",
        channel_type="webhook",
        config={"webhook_url": "https://example.com/db"},
    )

    if db_channel.group_id != db_group.id:
        channels_repo.update_channel(db_channel.id, {"group": db_group.id})

    infra_route = routes_repo.create_route_if_missing(
        team_id=infra.id,
        name="infra-alertmanager",
        source="alertmanager",
        rotation_id=infra_rotation.id,
        matchers={"labels": {"team": "infra"}},
        group_by=["alertname", "instance"],
    )

    db_route = routes_repo.create_route_if_missing(
        team_id=db_team.id,
        name="db-alertmanager",
        source="alertmanager",
        rotation_id=db_rotation.id,
        matchers={"labels": {"team": "db"}},
        group_by=["alertname", "instance"],
    )

    infra_token = ensure_route_token(infra_route)
    db_token = ensure_route_token(db_route)

    routes_repo.link_route_channel(infra_route.id, infra_channel.id)
    routes_repo.link_route_channel(db_route.id, db_channel.id)

    print(json.dumps({
        "status": "Demo data created",
        "admin": {
            "username": "admin",
            "password": "admin123",
            "group": None,
            "active_group": None,
        },
        "users": [
            {"username": "ivan", "password": "changeme123", "group": "infra", "active_group": "infra"},
            {"username": "petr", "password": "changeme123", "group": "infra", "active_group": "infra"},
            {"username": "sergey", "password": "changeme123", "group": "infra", "active_group": "infra"},
            {"username": "anna", "password": "changeme123", "group": "database", "active_group": "database"},
            {"username": "maria", "password": "changeme123", "group": "database", "active_group": "database"},
            {"username": "oleg", "password": "changeme123", "group": "database", "active_group": "database"},
        ],
        "route_tokens": {
            "infra-alertmanager": infra_token or "already exists; regenerate in Routes UI if needed",
            "db-alertmanager": db_token or "already exists; regenerate in Routes UI if needed",
        },
    }, indent=2))

    db.close()


def cmd_create_admin(args):
    """
    Create or update an admin user with a password.
    """

    db = init_database()
    db.connect(reuse_if_open=True)
    migrate()

    user = users_repo.get_user_by_username(args.username)

    data = {
        "username": args.username,
        "display_name": args.display_name or args.username,
        "email": args.email,
        "password_hash": hash_password(args.password),
        "is_admin": True,
        "active": True,
    }

    if user:
        user = users_repo.update_user(user.id, data)
    else:
        user = users_repo.create_user(**data)

    detach_user_from_groups(user)

    print(json.dumps({
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "group": None,
        "active_group": None,
    }, indent=2))
    db.close()


def cmd_set_password(args):
    """
    Set a user's password.
    """

    db = init_database()
    db.connect(reuse_if_open=True)

    user = users_repo.get_user_by_username(args.username)
    if not user:
        raise SystemExit(f"User {args.username} not found")

    users_repo.set_user_password(user.id, hash_password(args.password))
    print(json.dumps({"id": user.id, "username": user.username, "password": "updated"}, indent=2))
    db.close()

def main():
    """
    Run management commands.
    """

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--up-to")
    migrate_parser.set_defaults(func=cmd_migrate)

    status_parser = subparsers.add_parser("migration-status")
    status_parser.set_defaults(func=cmd_migration_status)

    create_migration_parser = subparsers.add_parser("create-migration")
    create_migration_parser.add_argument("name")
    create_migration_parser.set_defaults(func=lambda args: print(create_migration(args.name)))

    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--count", type=int, default=1)
    rollback_parser.set_defaults(func=lambda args: rollback(args.count))

    version_parser = subparsers.add_parser("version")
    version_parser.set_defaults(func=cmd_version)

    demo_parser = subparsers.add_parser("demo-data")
    demo_parser.set_defaults(func=cmd_demo_data)

    token_parser = subparsers.add_parser("create-token")
    token_parser.add_argument("--name", required=True)
    token_parser.add_argument("--team")
    token_parser.add_argument("--scopes", default="alerts:write")
    token_parser.add_argument("--days", type=int, default=0)
    token_parser.set_defaults(func=cmd_create_token)


    admin_parser = subparsers.add_parser("create-admin")
    admin_parser.add_argument("--username", required=True)
    admin_parser.add_argument("--password", required=True)
    admin_parser.add_argument("--email")
    admin_parser.add_argument("--display-name")
    admin_parser.set_defaults(func=cmd_create_admin)

    password_parser = subparsers.add_parser("set-password")
    password_parser.add_argument("--username", required=True)
    password_parser.add_argument("--password", required=True)
    password_parser.set_defaults(func=cmd_set_password)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
