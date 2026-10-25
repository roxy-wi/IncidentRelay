"""A failed multi-group merge must not leave partially moved child alerts."""

import pytest

from app.modules.db import alerts_repo
from app.modules.db.models import Alert, AlertGroup, AlertGroupMerge
from tests.factories import create_group, create_route, create_team, unique


def _group(team, route):
    return AlertGroup.create(
        team=team,
        route=route,
        source=route.source,
        group_key=unique("merge-key"),
        group_key_hash=unique("merge-hash"),
        title="Merge candidate",
        message="test",
        severity="critical",
        status="firing",
        alert_count=0,
        firing_count=0,
        common_labels={},
        label_values={},
        payload_summary={},
    )


def test_merge_rolls_back_when_saving_merge_record_fails(db, monkeypatch):
    team = create_team(create_group())
    route = create_route(team)
    target = _group(team, route)
    source = _group(team, route)
    # Even without a child Alert, source.status and merged_into must roll back.

    def fail_create(*args, **kwargs):
        raise RuntimeError("merge-record-write-failed")

    monkeypatch.setattr(AlertGroupMerge, "create", fail_create)

    with pytest.raises(RuntimeError, match="merge-record-write-failed"):
        alerts_repo.merge_alert_groups(
            target_group_id=target.id,
            source_group_ids=[source.id],
            user_id=None,
            reason="test rollback",
        )

    source = AlertGroup.get_by_id(source.id)
    assert source.status == "firing"
    assert source.merged_into_id is None
    assert AlertGroupMerge.select().count() == 0
    assert Alert.select().where(Alert.group == source.id).count() == 0
