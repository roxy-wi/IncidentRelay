"""Upgrade the scored-only schema without losing decisions or constraints."""

import importlib

import pytest
from peewee import IntegrityError
from playhouse.migrate import SchemaMigrator, migrate

from app.migrations.introspection import get_columns
from app.modules.db.models import ChangeAlertGroupCorrelation, ChangeIncidentLink
from tests.integrations.test_change_reviews import intake, review_case, setup_identity

__all__ = ["intake", "review_case", "setup_identity"]


def test_upgrade_preserves_suggestions_and_accepts_unscored_manual_links(
    db, review_case
):
    module = importlib.import_module("app.migrations.20261104010000_change_reviews")
    row = review_case.row
    with db.atomic() as transaction:
        ChangeIncidentLink.drop_table()
        migrate(
            SchemaMigrator.from_database(db).add_not_null(
                "change_alert_group_correlation", "score"
            )
        )
        module.upgrade()
        module.upgrade()
        restored = ChangeAlertGroupCorrelation.get_by_id(row.id)
        assert restored.__data__ == row.__data__
        ChangeAlertGroupCorrelation.update(score=None, reason="manual").where(
            ChangeAlertGroupCorrelation.id == row.id
        ).execute()
        link = ChangeIncidentLink.create(
            change=review_case.change,
            incident=review_case.incident,
            relation_type="context",
        )
        with pytest.raises(IntegrityError), db.atomic():
            ChangeIncidentLink.create(
                change=link.change_id,
                incident=link.incident_id,
                relation_type="mitigation",
            )
        for updates in ({"row_version": 0}, {"relation_type": "invalid"}):
            with pytest.raises(IntegrityError), db.atomic():
                ChangeIncidentLink.update(**updates).execute()
        module.downgrade()
        assert ChangeIncidentLink.select().count() == 1
        assert ChangeAlertGroupCorrelation.get_by_id(row.id).score is None
        transaction.rollback()


def test_failed_upgrade_rolls_back_schema_and_keeps_evidence(
    db, review_case, monkeypatch
):
    module = importlib.import_module("app.migrations.20261104010000_change_reviews")
    with db.atomic() as transaction:
        ChangeIncidentLink.drop_table()
        migrate(
            SchemaMigrator.from_database(db).add_not_null(
                "change_alert_group_correlation", "score"
            )
        )

        def fail(*args, **kwargs):
            raise RuntimeError("table creation unavailable")

        monkeypatch.setattr(db, "create_tables", fail)
        with pytest.raises(RuntimeError, match="table creation unavailable"):
            module.upgrade()
        score = next(
            column
            for column in get_columns(db, "change_alert_group_correlation")
            if column.name == "score"
        )
        assert not score.null
        assert (
            ChangeAlertGroupCorrelation.get_by_id(review_case.row.id).__data__
            == review_case.row.__data__
        )
        transaction.rollback()
