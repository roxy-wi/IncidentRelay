"""Timeline provenance is additive, constrained and restart safe."""

import importlib

import pytest
from peewee import ForeignKeyField, IntegrityError, Model

from app.modules.db.models import (
    AlertGroupEpisode,
    ChangeEvent,
    ChangeJob,
    ServiceEvent,
)
from app.services.service_catalog.timeline import publish_service_event
from tests.factories import create_group, create_service, create_team
from tests.integrations.test_changes_read import changes
from tests.integrations.test_change_events import intake, setup_identity
from tests.integrations.test_change_correlation import run_change

__all__ = ["changes", "intake", "setup_identity"]


def test_additive_upgrade_preserves_legacy_rows_and_rerun_does_not_requeue(db):
    service = create_service(create_team(create_group()))
    event = publish_service_event(
        service,
        category="legacy",
        event_type="legacy",
        title="Keep me",
        payload={"original": "data"},
    )
    original = ServiceEvent.get_by_id(event.id).__data__.copy()
    module = importlib.import_module(
        "app.migrations.20261104020000_change_service_timeline"
    )
    # Build the pre-upgrade schema. SQLite cannot drop an inline FK from the
    # fresh schema, and a table rebuild is not part of the production migration.
    fields = {}
    for name, field in ServiceEvent._meta.fields.items():
        if name not in {"change_event", "change_relation_type"}:
            fields[name] = field.clone()
            if isinstance(field, ForeignKeyField):
                fields[name].backref = "+"
    fields["Meta"] = type("Meta", (), {"database": db, "table_name": "service_event"})
    legacy = type("LegacyServiceEvent", (Model,), fields)
    with db.atomic() as transaction:
        ServiceEvent.drop_table()
        legacy.create_table()
        legacy.create(
            **{
                name: value
                for name, value in original.items()
                if name not in {"change_event", "change_relation_type"}
            }
        )
        module.upgrade()
        job = ChangeJob.get(ChangeJob.job_type == "discover_graph").__data__.copy()
        module.upgrade()
        assert ChangeJob.get(ChangeJob.job_type == "discover_graph").__data__ == job
        assert ServiceEvent.get_by_id(event.id).__data__ == original
        assert AlertGroupEpisode.select().count() == 0
        assert ChangeEvent.select().count() == 0
        transaction.rollback()


def test_provenance_foreign_key_and_uniqueness_are_enforced(db, changes):
    run_change(changes["change"], "sync_service_timeline")
    event = ServiceEvent.select().first()
    values = event.__data__.copy()
    values.pop("id")
    values.pop("uid")
    values["dedup_key"] = "other-dedup"
    with pytest.raises(IntegrityError), db.atomic():
        ServiceEvent.create(**values)
    with pytest.raises(IntegrityError), db.atomic():
        ServiceEvent.update(change_event=999999).where(
            ServiceEvent.id == event.id
        ).execute()
    with pytest.raises(IntegrityError), db.atomic():
        ServiceEvent.update(change_relation_type="unknown").where(
            ServiceEvent.id == event.id
        ).execute()
    with pytest.raises(IntegrityError), db.atomic():
        ChangeEvent.delete().execute()
