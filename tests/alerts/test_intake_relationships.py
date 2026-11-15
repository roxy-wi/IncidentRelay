from app.modules.db import alerts_repo
from app.modules.db.models import Alert, AlertGroup, AlertRoute, Team
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import create_group, create_route, create_team


def test_intake_reuses_loaded_relations_and_persists_foreign_keys(db, monkeypatch):
    team = create_team(create_group())
    route = create_route(team, source="webhook")
    captured = {}

    def wrap(name, create):
        def wrapped(**kwargs):
            row = create(**kwargs)
            assert isinstance(kwargs["team"], Team)
            assert isinstance(kwargs["route"], AlertRoute)
            if name == "alert":
                assert isinstance(kwargs["group"], AlertGroup)

            def unexpected(*args, **kwargs):
                raise AssertionError("Relations already loaded during intake must not be queried again")

            with monkeypatch.context() as patch:
                patch.setattr(db, "execute_sql", unexpected)
                assert row.team is kwargs["team"]
                assert row.route is kwargs["route"]
                if name == "alert":
                    assert row.group is kwargs["group"]
            captured[name] = row
            return row
        return wrapped

    monkeypatch.setattr(alerts_repo, "create_alert_group", wrap("group", alerts_repo.create_alert_group))
    monkeypatch.setattr(alerts_repo, "create_alert", wrap("alert", alerts_repo.create_alert))
    result = upsert_alert({
        "source": "webhook", "forced_route_id": route.id,
        "dedup_key": "loaded-relations", "title": "Loaded relations",
        "external_id": "loaded-relations", "status": "firing", "labels": {}, "payload": {},
    })
    assert result.alert.id == captured["alert"].id
    stored_alert = Alert.get_by_id(result.alert.id)
    stored_group = AlertGroup.get_by_id(result.group.id)
    assert (stored_alert.team_id, stored_alert.route_id, stored_alert.group_id) == (team.id, route.id, stored_group.id)
    assert (stored_group.team_id, stored_group.route_id) == (team.id, route.id)
