"""Regression coverage for readiness transactions under SQLite contention."""

import sqlite3

import pytest

from app.modules.db.models import (
    Service,
    ServiceReadinessCheckResult,
    ServiceReadinessEvaluation,
    ServiceReadinessState,
)
from app.services.service_catalog import readiness
from tests.factories import create_group, create_service, create_team
from tests.services.service_catalog.test_readiness import create_check, create_standard


def _service_with_standard():
    group = create_group()
    service = create_service(create_team(group))
    standard = create_standard(group)
    create_check(
        standard,
        slug="name-present",
        check_type="field_present",
        configuration={"field": "name"},
    )
    return service


def test_readiness_survives_a_competing_writer(monkeypatch):
    """A write between check reads and result inserts must not break evaluation."""
    service = _service_with_standard()
    database = Service._meta.database
    other_connection = sqlite3.connect(database.database, timeout=0)
    evaluate_check = readiness.evaluate_check
    write_attempts = []

    def evaluate_with_competing_write(service, check):
        outcome = evaluate_check(service, check)
        try:
            other_connection.execute(
                "UPDATE service SET description = ? WHERE id = ?",
                ("Concurrent update", service.id),
            )
            other_connection.commit()
        except sqlite3.OperationalError as exc:
            other_connection.rollback()
            if "locked" not in str(exc):
                raise
            write_attempts.append("deferred")
        else:
            write_attempts.append("committed")
        return outcome

    monkeypatch.setattr(readiness, "evaluate_check", evaluate_with_competing_write)
    try:
        result = readiness.evaluate_service_readiness(service)
        assert result["state"].status == "ready"
        assert len(result["evaluations"]) == 1
        assert len(write_attempts) == 1
        assert ServiceReadinessCheckResult.select().count() == 1

        # The competing update can complete once evaluation releases its lock.
        other_connection.execute(
            "UPDATE service SET description = ? WHERE id = ?",
            ("Concurrent update", service.id),
        )
        other_connection.commit()
        assert Service.get_by_id(service.id).description == "Concurrent update"
    finally:
        other_connection.close()


def test_readiness_rolls_back_all_results_if_state_save_fails(monkeypatch):
    """A failed batch must leave neither partial results nor a write lock."""
    service = _service_with_standard()

    def fail_state_save(*args, **kwargs):
        raise RuntimeError("State save failed")

    with monkeypatch.context() as patch:
        patch.setattr(readiness, "_save_readiness_state", fail_state_save)
        with pytest.raises(RuntimeError, match="State save failed"):
            readiness.evaluate_service_readiness(service)

    assert ServiceReadinessEvaluation.select().count() == 0
    assert ServiceReadinessCheckResult.select().count() == 0
    assert ServiceReadinessState.select().count() == 0
    assert readiness.evaluate_service_readiness(service)["state"].status == "ready"
