import pytest

from app.modules.db.models import Alert, AlertExplainTrace
from app.services.alerts import correlation
from app.services.alerts.lifecycle import upsert_alert
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
