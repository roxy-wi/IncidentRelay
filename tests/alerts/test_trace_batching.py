import pytest

from app.modules.db import alerts_repo, incidents_repo, routes_repo
from app.modules.db.models import IncidentPriority
from app.services.alerts.explain import AlertExplainTrace
from app.services.integrations.auth import hash_token
from tests.factories import create_group, create_route, create_team


@pytest.mark.parametrize("level", ["full", "compact"])
def test_buffered_trace_batches_steps_without_losing_order_or_data(db, monkeypatch, level):
    trace = AlertExplainTrace.start_buffered({"source": "test", "labels": {}})
    trace.apply_level(level)
    inserts = []
    execute = db.execute_sql

    def count(sql, params=None, *args, **kwargs):
        if sql.startswith('INSERT INTO "alertexplainstep"'):
            inserts.append(sql)
        return execute(sql, params, *args, **kwargs)

    monkeypatch.setattr(db, "execute_sql", count)
    for index in range(120):
        trace.step("test", str(index), "success", "Test", value=index)
    trace.finish(outcome="created")
    rows = list(alerts_repo.list_alert_explain_steps(trace.row))
    assert len(rows) == 121  # received plus the 120 explicit steps
    assert [row.position for row in rows] == list(range(1, 122))
    assert [row.code for row in rows[1:]] == [str(i) for i in range(120)]
    assert rows[-1].data == ({"value": 119} if level == "full" else {})
    assert len(inserts) == 3


def test_bad_diagnostic_row_does_not_discard_other_steps_or_poison_transaction(db):
    trace = AlertExplainTrace.start_buffered({"source": "test"})
    trace.apply_level("full")
    trace.step("test", None, "success", "Invalid code")
    trace.step("test", "survives", "success", "Valid step")
    with db.atomic():
        trace.finish(outcome="created")
        assert db.execute_sql("SELECT 1").fetchone() == (1,)
    assert [row.code for row in alerts_repo.list_alert_explain_steps(trace.row)] == [
        "alert_received", "survives",
    ]
    assert alerts_repo.get_alert_explain_trace(trace.trace_id).status == "completed"


def test_failed_processing_flushes_diagnostics(db):
    trace = AlertExplainTrace.start_buffered({"source": "test"})
    trace.apply_level("compact")
    trace.step("test", "before_failure", "success", "Before failure", sensitive="omitted")
    trace.fail(RuntimeError("failed processing"))
    rows = list(alerts_repo.list_alert_explain_steps(trace.row))
    assert rows[-1].code == "processing_exception"
    assert all(row.data == {} for row in rows)
    assert alerts_repo.get_alert_explain_trace(trace.trace_id).status == "failed"


def test_priority_seed_preserves_customized_rows_and_restores_missing_defaults(db):
    incidents_repo.ensure_default_priorities()
    IncidentPriority.update(name="Custom critical", enabled=False).where(IncidentPriority.slug == "p1").execute()
    IncidentPriority.delete().where(IncidentPriority.slug == "p5").execute()
    incidents_repo.ensure_default_priorities()
    critical = IncidentPriority.get(IncidentPriority.slug == "p1")
    assert (critical.name, critical.enabled) == ("Custom critical", False)
    assert IncidentPriority.select().where(IncidentPriority.slug == "p5").exists()


def test_intake_route_hydrates_team_and_group_without_bypassing_activity_checks(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, token_hash=hash_token("test-route"))
    fetched = routes_repo.get_route_by_intake_hash(hash_token("test-route"))
    execute = db.execute_sql

    def unexpected(*args, **kwargs):
        raise AssertionError("related team/group should already be loaded")

    monkeypatch.setattr(db, "execute_sql", unexpected)
    assert fetched.id == route.id
    assert fetched.team.id == team.id
    assert fetched.team.group.id == group.id
    monkeypatch.setattr(db, "execute_sql", execute)
    group.active = False
    group.save()
    assert routes_repo.get_route_by_intake_hash(hash_token("test-route")) is None
