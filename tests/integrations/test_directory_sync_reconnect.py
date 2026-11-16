"""Retained imports reconnect atomically, preserving identities and ownership."""

from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import (
    DirectorySyncBinding as Binding, DirectorySyncShift as Shift,
    DirectorySyncSource as Source, Rotation, Team, TeamUser, User,
)
from app.services.directory_sync import service
from app.services.directory_sync.config import SyncError
from app.services.directory_sync.runtime import source_for
from tests.factories import create_group, create_team
from tests.integrations.test_directory_sync import (
    binding,
    fetched as fetched,
    snapshot as snapshot,
    source as source,
)
from tests.integrations.test_directory_sync_management import remove

URL = "/api/admin/directory-sync"


def recreate(client, headers, original, **config):
    response = client.post(URL, headers=headers, json={
        "name": original.name, "group_id": original.group_id,
        "config": {**original.config, "retained_source_id": original.id, **config},
    })
    assert response.status_code == 201, response.json
    return Source.get_by_id(response.json["id"])


def apply_preview(source):
    preview = service.run(source.id, mode="preview")
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    return preview


@pytest.mark.parametrize("matched_team", [False, True])
def test_reconnect_preserves_ids_history_and_deletion_provenance(
    client, admin_headers, source, fetched, snapshot, matched_team,
):
    if matched_team:
        create_team(group=source.group, name="Platform")
        source.config["overwrite_existing"] = True
        source.save()
    service.run(source.id)
    old_bindings = {(row.kind, row.external_id): row.local_id for row in Binding.select().where(Binding.source == source.id)}
    team_id = binding(source, "team", "t1").local_id
    rotation_id = binding(source, "rotation", "s1").local_id
    shift_id = Shift.get(Shift.external_id == "shift1").id
    historical = Shift.create(
        source=source, rotation=rotation_id, external_id="historical-local", title="Local history",
        user=binding(source, "user", "u2").local_id,
        starts_at=utc_now() - timedelta(days=400), ends_at=utc_now() - timedelta(days=399),
        local_override=True, replacements=[{"id": "history", "user_id": binding(source, "user", "u1").local_id,
                                          "start": "2020-01-01T00:00:00Z", "end": "2020-01-02T00:00:00Z"}],
    )
    original_history = Shift.get_by_id(historical.id).__data__.copy()
    assert remove(client, admin_headers, source).status_code == 200
    Team.update(name="Locally renamed team").where(Team.id == team_id).execute()
    Rotation.update(name="Locally renamed schedule").where(Rotation.id == rotation_id).execute()
    snapshot["users"][0]["email"] = "new-email@example.com"
    created = recreate(client, admin_headers, source, overwrite_existing=False)
    old_rows = list(Binding.select().where(Binding.source == source.id).dicts())
    preview = service.run(created.id, mode="preview")
    assert not Binding.select().where(Binding.source == created.id).exists()
    assert list(Binding.select().where(Binding.source == source.id).dicts()) == old_rows
    assert Shift.get_by_id(shift_id).source_id == source.id
    assert Team.get_by_id(team_id).name == "Locally renamed team"
    changes = preview["changes"]
    assert {row["kind"] for row in changes if row["action"] == "reconnect"} == {"team", "rotation", "shift"}
    assert not any(row["action"] == "create" for row in changes)
    service.run(created.id, mode="apply", preview_token=preview["preview_token"])
    new_bindings = {(row.kind, row.external_id): row.local_id for row in Binding.select().where(Binding.source == created.id)}
    assert new_bindings == old_bindings
    assert source_for("rotation", rotation_id).id == created.id
    assert source_for("team", team_id).id == created.id
    assert Team.get_by_id(team_id).name == "Platform"
    assert Rotation.get_by_id(rotation_id).name == "Slot 1"
    assert User.get_by_id(binding(created, "user", "u1").local_id).email == "new-email@example.com"
    assert Shift.get_by_id(shift_id).source_id == created.id
    assert Shift.get_by_id(historical.id).__data__ == {**original_history, "source": created.id}
    assert not Binding.select().where(Binding.source == source.id, Binding.present == True).exists()
    assert binding(created, "team", "t1").created is not matched_team
    assert binding(created, "team_member", next(key for kind, key in old_bindings if kind == "team_member")).owned
    assert TeamUser.select().where(TeamUser.team == team_id).count() == 1
    assert service.run(created.id)["changes"] == []
    assert (Team.select().count(), Rotation.select().count(), Shift.select().count()) == (1, 2, 2)
    assert client.get(URL + "/options", headers=admin_headers).json["retained_sources"] == []
    assert remove(client, admin_headers, created, "delete").status_code == 200
    assert Team.get_by_id(team_id).deleted is not matched_team


def test_two_previews_cannot_claim_the_same_retained_data(client, admin_headers, source, fetched):
    service.run(source.id)
    assert remove(client, admin_headers, source).status_code == 200
    first = recreate(client, admin_headers, source)
    second = recreate(client, admin_headers, source)
    first_preview = service.run(first.id, mode="preview")
    second_preview = service.run(second.id, mode="preview")
    service.run(first.id, mode="apply", preview_token=first_preview["preview_token"])
    with pytest.raises(SyncError, match="no longer available"):
        service.run(second.id, mode="apply", preview_token=second_preview["preview_token"])
    assert not Binding.select().where(Binding.source == second.id).exists()
    assert Shift.get().source_id == first.id
    assert Rotation.select().count() == 2


def test_reconnect_failure_rolls_back_transfer(client, admin_headers, source, fetched):
    service.run(source.id)
    other = create_team(group=source.group, name="Different team")
    assert remove(client, admin_headers, source).status_code == 200
    created = recreate(client, admin_headers, source, team_matches={"t1": other.id})
    with pytest.raises(SyncError, match="stable local match"):
        service.run(created.id, mode="preview")
    assert not Binding.select().where(Binding.source == created.id).exists()
    assert binding(source, "rotation", "s1").present
    assert Shift.get().source_id == source.id


def test_reconnect_detects_changes_after_preview(client, admin_headers, source, fetched):
    service.run(source.id)
    assert remove(client, admin_headers, source).status_code == 200
    created = recreate(client, admin_headers, source)
    preview = service.run(created.id, mode="preview")
    Shift.update(title="Edited after preview").execute()
    with pytest.raises(SyncError, match="Local data changed since preview"):
        service.run(created.id, mode="apply", preview_token=preview["preview_token"])
    assert Shift.get().title == "Edited after preview"
    assert Shift.get().source_id == source.id
    assert not Binding.select().where(Binding.source == created.id).exists()


@pytest.mark.parametrize("kind", ["team", "rotation"])
def test_reconnect_refuses_another_owner(client, admin_headers, source, fetched, kind):
    service.run(source.id)
    assert remove(client, admin_headers, source).status_code == 200
    created = recreate(client, admin_headers, source)
    owner = Source.create(name="Another owner", group=source.group, config=source.config, created_by=source.created_by)
    key = "t1" if kind == "team" else "s1"
    Binding.create(source=owner, kind=kind, external_id="different", local_id=binding(source, kind, key).local_id)
    with pytest.raises(SyncError, match="another synchronization source"):
        service.run(created.id, mode="preview")
    assert Shift.get().source_id == source.id


def test_reconnect_refuses_resources_moved_to_another_group(client, admin_headers, source, fetched):
    service.run(source.id)
    assert remove(client, admin_headers, source).status_code == 200
    created = recreate(client, admin_headers, source)
    Team.update(group=create_group().id).where(Team.id == binding(source, "team", "t1").local_id).execute()
    with pytest.raises(SyncError, match="outside the destination group"):
        service.run(created.id, mode="preview")
    assert Shift.get().source_id == source.id


@pytest.mark.parametrize("state", ["active", "foreign", "missing"])
def test_only_archived_sources_in_same_group_can_be_selected(client, admin_headers, source, state):
    source.deleted = state != "active"
    source.save()
    response = client.post(URL, headers=admin_headers, json={
        "name": "New", "group_id": create_group().id if state == "foreign" else source.group_id,
        "config": {**source.config, "retained_source_id": source.id + 1000 if state == "missing" else source.id},
    })
    assert response.status_code == 409
    assert Source.select().count() == 1


@pytest.mark.parametrize("value", [True, "1", 0, -1, 1.5])
def test_retained_source_id_is_strict(client, admin_headers, source, value):
    response = client.post(URL, headers=admin_headers, json={
        "name": "New", "group_id": source.group_id, "config": {**source.config, "retained_source_id": value},
    })
    assert response.status_code == 400


def test_reconnect_selection_is_preview_critical_then_immutable(client, admin_headers, source, fetched):
    service.run(source.id)
    assert remove(client, admin_headers, source).status_code == 200
    created = recreate(client, admin_headers, source, retained_source_id=None)
    service.run(created.id, mode="preview")
    response = client.put(f"{URL}/{created.id}", headers=admin_headers, json={
        "name": created.name, "group_id": created.group_id, "revision": created.revision,
        "config": {**created.config, "retained_source_id": source.id},
    })
    assert response.status_code == 200
    assert response.json["preview_token"] is None
    apply_preview(created)
    created = Source.get_by_id(created.id)
    for selected, status in [(None, 409), (source.id, 200)]:
        response = client.put(f"{URL}/{created.id}", headers=admin_headers, json={
            "name": created.name, "group_id": created.group_id, "revision": created.revision,
            "config": {**created.config, "retained_source_id": selected, "editable": True},
        })
        assert response.status_code == status
    assert response.json["approved"]


@pytest.mark.parametrize("legacy", [False, True])
def test_repeated_keep_and_reconnect_preserves_ids(client, admin_headers, source, fetched, legacy):
    service.run(source.id)
    rotation_id = binding(source, "rotation", "s1").local_id
    for _ in range(2):
        source = Source.get_by_id(source.id)
        assert remove(client, admin_headers, source).status_code == 200
        if legacy:
            # Simulate a source deleted before explicit retention metadata existed.
            source = Source.get_by_id(source.id)
            source.last_result.pop("retained_team_ids")
            source.save()
        options = client.get(URL + "/options", headers=admin_headers).json["retained_sources"]
        assert [item["id"] for item in options] == [source.id]
        assert set(options[0]) == {"id", "name", "group_id", "base_url"}
        source = recreate(client, admin_headers, source)
        apply_preview(source)
        assert binding(source, "rotation", "s1").local_id == rotation_id
    assert Rotation.select().count() == 2
    assert Shift.select().count() == 1


def test_matched_team_without_schedules_can_be_reconnected_repeatedly(
    client, admin_headers, source, fetched, snapshot,
):
    existing = create_team(group=source.group, name="Platform")
    source.config["overwrite_existing"] = True
    source.save()
    snapshot["teams"][0]["schedules"] = []
    snapshot["teams"][0]["shifts"] = []
    service.run(source.id)
    for _ in range(2):
        source = Source.get_by_id(source.id)
        assert remove(client, admin_headers, source).status_code == 200
        assert [item["id"] for item in client.get(URL + "/options", headers=admin_headers).json["retained_sources"]] == [source.id]
        source = recreate(client, admin_headers, source, overwrite_existing=False)
        apply_preview(source)
        assert binding(source, "team", "t1").local_id == existing.id
        assert binding(source, "team", "t1").owned
        assert not binding(source, "team", "t1").created
        assert service.run(source.id)["changes"] == []
    assert Team.select().count() == 1
    assert Rotation.select().count() == 0


def test_retained_schedules_reconnect_after_matched_team_management_was_disabled(
    client, admin_headers, source, fetched,
):
    team = create_team(group=source.group, name="Platform")
    source.config["overwrite_existing"] = True
    source.save()
    service.run(source.id)
    rotation_id = binding(source, "rotation", "s1").local_id
    shift_id = Shift.get().id
    source = Source.get_by_id(source.id)
    source.config["overwrite_existing"] = False
    source.save()
    service.run(source.id)
    assert not binding(source, "team", "t1").owned
    assert binding(source, "rotation", "s1").owned
    assert remove(client, admin_headers, source).status_code == 200

    options = client.get(URL + "/options", headers=admin_headers).json["retained_sources"]
    assert [item["id"] for item in options] == [source.id]
    created = recreate(client, admin_headers, source)
    preview = apply_preview(created)
    assert not any(item["action"] == "create" for item in preview["changes"])
    assert binding(created, "team", "t1").local_id == team.id
    assert binding(created, "rotation", "s1").local_id == rotation_id
    assert Shift.get().id == shift_id
    assert Shift.get().source_id == created.id
    assert service.run(created.id)["changes"] == []


@pytest.mark.parametrize("delete_missing", [False, True])
def test_absent_retained_schedule_follows_deletion_policy(client, admin_headers, source, fetched, snapshot, delete_missing):
    service.run(source.id)
    rotation_id = binding(source, "rotation", "s2").local_id
    assert remove(client, admin_headers, source).status_code == 200
    snapshot["teams"][0]["schedules"].pop()
    created = recreate(client, admin_headers, source, delete_missing=delete_missing)
    apply_preview(created)
    assert Rotation.get_by_id(rotation_id).deleted is delete_missing
    assert Rotation.select().count() == 2


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_shift_writes_recheck_ownership_after_reconnection(
    client, admin_headers, source, fetched, monkeypatch, method,
):
    service.run(source.id)
    shift = Shift.get()
    assert remove(client, admin_headers, source).status_code == 200
    created = recreate(client, admin_headers, source, editable=False)
    preview = service.run(created.id, mode="preview")
    original_lock = service.apply_lock

    def reconnect_before_edit():
        # Complete the competing Apply after the request's permission check but
        # before the shift writer resolves its source under the shared lock.
        monkeypatch.setattr(service, "apply_lock", original_lock)
        service.run(created.id, mode="apply", preview_token=preview["preview_token"])
        original_lock()

    monkeypatch.setattr(service, "apply_lock", reconnect_before_edit)
    url = (f"/api/rotations/{shift.rotation_id}/imported-shifts" if method == "POST"
           else f"/api/rotations/imported-shifts/{shift.id}")
    response = client.open(url, method=method, headers=admin_headers, json={
        "user_id": shift.user_id, "start": shift.starts_at.isoformat() + "Z",
        "end": shift.ends_at.isoformat() + "Z", "title": "Stale local edit",
    })
    assert response.status_code == 409
    assert "read-only" in response.json["message"]
    assert Shift.select().count() == 1
    assert not Shift.get().deleted
    assert Shift.get().title != "Stale local edit"
