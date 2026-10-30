"""Real connections serialize technical cycles without losing episode work."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from app.db import database_proxy
from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
    AlertGroupEpisode,
    ChangeJob,
)
from app.services.alerts import actions, lifecycle
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.runtime import RuntimeResult
from tests.factories import create_group, create_route, create_team, unique
from tests.alerts.test_alert_episodes import _remove_episode_tracking


pytestmark = pytest.mark.postgresql


@pytest.fixture
def incoming(db, monkeypatch):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")
    team = create_team(create_group())
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": unique("event"),
        "dedup_key": unique("key"),
        "title": "Disk full",
        "severity": "critical",
        "status": "firing",
        "labels": {"alertname": "DiskFull"},
        "payload": {},
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_two_reopens_create_one_episode_and_one_discovery_request(incoming, legacy):
    first = upsert_alert(dict(incoming))
    if legacy:
        _remove_episode_tracking(first.group)
    upsert_alert(dict(incoming, status="resolved"))
    barrier = Barrier(2)

    def reopen():
        with database_proxy.obj.connection_context():
            barrier.wait(timeout=10)
            return upsert_alert(dict(incoming))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reopen) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]

    current = AlertGroup.get_by_id(first.group.id).current_episode
    assert all(result.group.id == first.group.id for result in results)
    expected_episodes = 1 if legacy else 2
    assert current.ordinal == expected_episodes and current.state == "open"
    assert AlertGroupEpisode.select().count() == expected_episodes
    assert Alert.select().where(Alert.group == first.group.id).count() == 2
    job = ChangeJob.get(
        ChangeJob.job_type == "discover_episode", ChangeJob.entity_id == current.id
    )
    assert job.requested_generation == 1


def test_concurrent_child_recoveries_close_one_episode(incoming):
    first = upsert_alert(dict(incoming))
    other = dict(incoming, dedup_key=unique("second"))
    second = upsert_alert(dict(other))
    assert second.group.id == first.group.id
    episode_id = first.group.current_episode_id
    barrier = Barrier(2)

    def resolve(data):
        with database_proxy.obj.connection_context():
            barrier.wait(timeout=10)
            return upsert_alert(dict(data, status="resolved"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(resolve, data) for data in (incoming, other)]
        for future in futures:
            future.result(timeout=30)

    group = AlertGroup.get_by_id(first.group.id)
    episode = AlertGroupEpisode.get_by_id(episode_id)
    assert group.status == "resolved" and group.current_episode_id is None
    assert group.resolved_count == 2
    assert episode.state == "resolved" and episode.ended_at == group.resolved_at
    job = ChangeJob.get(
        ChangeJob.job_type == "discover_episode", ChangeJob.entity_id == episode_id
    )
    assert job.requested_generation == 2
    assert AlertEvent.select().where(AlertEvent.event_type == "resolved").count() == 2


@pytest.mark.parametrize("legacy", [False, True])
def test_manual_resolve_cannot_close_a_cycle_started_while_it_waited(
    incoming, monkeypatch, legacy
):
    initial = upsert_alert(dict(incoming))
    if legacy:
        initial.group = _remove_episode_tracking(initial.group)
    waiting = Event()
    release = Event()
    original_lock = actions._lock_group_for_lifecycle

    def wait_before_lock(group_id):
        waiting.set()
        assert release.wait(timeout=20)
        return original_lock(group_id)

    monkeypatch.setattr(actions, "_lock_group_for_lifecycle", wait_before_lock)

    def resolve():
        with database_proxy.obj.connection_context():
            return actions.resolve_alert(initial.group.id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(resolve)
        try:
            assert waiting.wait(timeout=10)
            upsert_alert(dict(incoming, status="resolved"))
            reopened = upsert_alert(dict(incoming))
        finally:
            release.set()
        result = future.result(timeout=30)

    group = AlertGroup.get_by_id(initial.group.id)
    assert result.status == group.status == "firing"
    assert group.current_episode_id == reopened.group.current_episode_id
    assert group.current_episode_id != initial.group.current_episode_id
    assert group.current_episode.state == "open"
    assert Alert.get_by_id(reopened.alert.id).status == "firing"
    assert AlertEvent.select().where(AlertEvent.event_type == "resolved").count() == 1
