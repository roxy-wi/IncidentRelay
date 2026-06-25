import pytest
import importlib.util
from pathlib import Path

from peewee import IntegrityError, ForeignKeyField

from app.modules.db.models import Group, NotificationChannel, Team, UserGroup
from tests.factories import create_channel, create_group, create_team, create_user


def test_group_slug_is_unique(db):
    create_group(name="Infra", slug="infra")

    with pytest.raises(IntegrityError):
        create_group(name="Infra duplicate", slug="infra")


def test_user_can_belong_to_group(db):
    group = create_group(slug="infra")
    user = create_user(username="ivan", group=group)

    assert UserGroup.select().where(UserGroup.user == user, UserGroup.group == group).exists()
    assert user.active_group == group


def test_team_belongs_to_group(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")

    fetched = Team.get_by_id(team.id)

    assert fetched.group == group
    assert fetched.slug == "sre"


def test_json_field_round_trip_for_channel_config(db):
    group = create_group(slug="infra")
    channel = create_channel(
        group,
        config={
            "webhook_url": "https://example.com/webhook",
            "headers": {"X-Test": "yes"},
            "enabled": True,
            "retries": [1, 2, 3],
        },
    )

    fetched = NotificationChannel.get_by_id(channel.id)

    assert fetched.config["headers"]["X-Test"] == "yes"
    assert fetched.config["enabled"] is True
    assert fetched.config["retries"] == [1, 2, 3]


def test_active_flags_default_to_enabled(db):
    group = Group.create(name="Infra", slug="infra")
    user = create_user(username="alice", group=group)
    team = create_team(group, slug="sre")

    assert group.active is True
    assert user.active is True
    assert team.active is True


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "migrations"
    / "20260427000001_initial_schema.py"
)


def load_initial_migration():
    spec = importlib.util.spec_from_file_location(
        "initial_schema_migration",
        MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initial_schema_includes_foreign_key_dependencies():
    migration = load_initial_migration()
    models = migration.BOOTSTRAP_MODELS
    positions = {model: index for index, model in enumerate(models)}

    for model in models:
        for field in model._meta.sorted_fields:
            if not isinstance(field, ForeignKeyField):
                continue

            related_model = field.rel_model

            if related_model is model:
                continue

            assert related_model in positions, (
                f"{model.__name__}.{field.name} references "
                f"{related_model.__name__}, but it is not included "
                "in the initial schema"
            )

            assert positions[related_model] < positions[model], (
                f"{related_model.__name__} must be created before "
                f"{model.__name__}"
            )


def test_alert_route_dependencies_are_in_initial_schema():
    migration = load_initial_migration()
    model_names = {
        model.__name__
        for model in migration.BOOTSTRAP_MODELS
    }

    assert "EscalationPolicy" in model_names
    assert "Service" in model_names
