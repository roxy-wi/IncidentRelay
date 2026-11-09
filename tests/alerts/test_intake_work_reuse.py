import pytest

from app.modules.db import alerts_repo
from app.modules.db.models import Alert, AlertExplainTrace, AlertGroup
from app.services.alerts import correlation
from app.services.alerts.lifecycle import _sync_orchestration_group_fields, upsert_alert
from tests.factories import create_group, create_route, create_team


@pytest.mark.parametrize("fails", [False, True])
def test_new_alert_refreshes_correlations_once_and_isolates_refresh_failure(db, monkeypatch, fails):
    route = create_route(create_team(create_group()), source="webhook")
    calls = []
    deactivate = correlation._deactivate_stale_correlations

    def counted(group, *args, **kwargs):
        calls.append(group.id)
        if fails:
            raise RuntimeError("correlation unavailable")
        return deactivate(group, *args, **kwargs)

    monkeypatch.setattr(correlation, "_deactivate_stale_correlations", counted)
    result = upsert_alert({
        "source": "webhook", "forced_route_id": route.id,
        "dedup_key": "one-correlation-refresh", "title": "Single refresh",
        "status": "firing", "labels": {}, "payload": {},
    })
    assert calls == [result.group.id]
    assert Alert.get_by_id(result.alert.id).group_id == result.group.id
    assert AlertExplainTrace.get_by_id(result.trace.row.id).status == "completed"


def test_orchestration_state_skips_unchanged_writes_and_persists_dirty_values(db, monkeypatch):
    group = alerts_repo.create_alert_group(source="test", group_key="unchanged", title="Unchanged")
    calls = []
    execute = db.execute_sql

    def capture(sql, params=None, *args, **kwargs):
        calls.append(sql)
        return execute(sql, params, *args, **kwargs)

    monkeypatch.setattr(db, "execute_sql", capture)
    _sync_orchestration_group_fields(group, runtime=None, suppressed=False, reason=None)
    assert calls == []
    _sync_orchestration_group_fields(group, runtime=None, suppressed=True, reason="maintenance")
    assert len(calls) == 1
    fetched = AlertGroup.get_by_id(group.id)
    assert (fetched.orchestration_suppressed, fetched.orchestration_suppress_reason) == (True, "maintenance")
    calls.clear()
    # A caller may have assigned the desired value without saving it yet.
    fetched.orchestration_suppress_reason = "changed-before-sync"
    _sync_orchestration_group_fields(fetched, runtime=None, suppressed=True, reason="changed-before-sync")
    assert len(calls) == 1
    assert AlertGroup.get_by_id(group.id).orchestration_suppress_reason == "changed-before-sync"
