"""Upgrade is additive, idempotent, and never reconstructs older episodes."""

import importlib

import pytest
from peewee import IntegrityError

from app.migrations.introspection import get_indexes
from app.modules.db.models import (
    AlertGroup,
    AlertGroupEpisode,
    ChangeImpact,
    ChangeAlertGroupCorrelation,
    Service,
)
from tests.factories import create_group, create_service, create_team, unique
from tests.integrations.test_change_correlation import (
    episode_for,
    intake,
    operation,
    opt_in,
    run_change,
    setup_identity,
)

__all__ = ["intake", "setup_identity"]


def test_upgrade_preserves_legacy_children_and_does_not_backfill(db):
    team = create_team(create_group())
    service = create_service(team)
    episode = episode_for(service)
    group_id = episode.alert_group_id
    module = importlib.import_module(
        "app.migrations.20261103010000_change_correlations"
    )
    with db.atomic() as transaction:
        ChangeAlertGroupCorrelation.drop_table()
        ChangeImpact.drop_table()
        for index in get_indexes(db, "alert_group_episode"):
            if "correlation_service_id" in index.columns:
                name = index.name.replace('"', '""')
                db.execute_sql(f'DROP INDEX "{name}"')
        for table, columns in (
            (
                "service",
                ["change_correlation_enabled", "change_correlation_exclusions"],
            ),
            (
                "alert_group_episode",
                ["correlation_context", "correlation_service_id", "context_revision"],
            ),
        ):
            for column in columns:
                db.execute_sql(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
        module.upgrade()
        module.upgrade()
        assert AlertGroup.get_by_id(group_id).current_episode_id == episode.id
        assert AlertGroupEpisode.select().count() == 1
        restored = AlertGroupEpisode.get_by_id(episode.id)
        assert restored.correlation_context is None
        assert (
            restored.correlation_service_id is None and restored.context_revision == 1
        )
        assert restored.started_at == episode.started_at
        assert restored.alert_group.alerts.count() == 1
        assert Service.get_by_id(service.id).change_correlation_enabled is False
        assert Service.get_by_id(service.id).change_correlation_exclusions == []
        transaction.rollback()


def test_pair_uniqueness_and_constraints(intake, db):
    service = opt_in(intake[0][2])
    episode_for(service)
    change = operation(intake)
    run_change(change)
    row = ChangeAlertGroupCorrelation.get()
    with pytest.raises(IntegrityError), db.atomic():
        ChangeAlertGroupCorrelation.create(
            change=change,
            episode=row.episode_id,
            score=90,
            reason="changed",
            engine_version="test",
        )
    for updates in (
        {"score": 101},
        {"review_status": "auto_confirmed"},
        {"row_version": 0},
        {"relation_type": "invalid"},
    ):
        with pytest.raises(IntegrityError), db.atomic():
            ChangeAlertGroupCorrelation.update(**updates).where(
                ChangeAlertGroupCorrelation.id == row.id
            ).execute()
    with pytest.raises(IntegrityError), db.atomic():
        ChangeImpact.update(depth=6).execute()
