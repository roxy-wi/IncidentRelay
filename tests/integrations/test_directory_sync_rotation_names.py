"""Imported schedule identities survive reordered and renamed rotation names."""

import copy
from types import SimpleNamespace

import pytest

from app.modules.db.models import DirectorySyncShift as Shift, Rotation
from app.services.sync.directory import service
from app.services.sync.directory.config import SyncConfig, SyncError
from app.services.sync.directory.fetch import fetch_snapshot
from tests.integrations.test_directory_sync import (
    binding,
    fetched as fetched,
    snapshot as snapshot,
    source as source,
)


def rotation_state():
    """Capture persisted names and identities without query iteration across writes."""
    return list(Rotation.select().order_by(Rotation.id).dicts())


def apply_preview(source):
    preview = service.run(source.id, mode="preview")
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    return preview


def test_reordered_unnamed_api_schedules_keep_rotation_ids(source, monkeypatch):
    order = ["s1", "s2"]
    config = SyncConfig.model_validate(source.config)
    detail = {"name": "Platform", "enabled": True, "roster": [], "responsible": None}
    client = SimpleNamespace(
        config=config,
        records=lambda operation, _context: (
            [{"enrolledScopeUuid": "t1", "name": "Platform"}] if operation == "teams" else []
        ),
        request=lambda *_args: {**detail, "schedules": [{"uuid": key} for key in order]},
    )
    monkeypatch.setattr(service, "fetch_snapshot", lambda _client: fetch_snapshot(client))
    apply_preview(source)
    ids = {key: binding(source, "rotation", key).local_id for key in order}
    before = rotation_state()
    order.reverse()
    preview = service.run(source.id, mode="preview")
    assert rotation_state() == before
    changes = [item for item in preview["changes"] if item["kind"] == "rotation"]
    assert {item["external_id"] for item in changes} == set(ids)
    assert all(item["action"] == "update" for item in changes)
    assert changes[0]["fields"]["name"] == {"before": "Platform / 2", "after": "Platform / 1"}
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    for number, key in enumerate(order, 1):
        assert binding(source, "rotation", key).local_id == ids[key]
        assert Rotation.get_by_id(ids[key]).name == f"Platform / {number}"
    assert Rotation.select().count() == 2
    assert service.run(source.id)["changes"] == []


@pytest.mark.parametrize("reverse_order", [False, True])
def test_cyclic_rename_preserves_shift_links_and_preview(source, fetched, snapshot, reverse_order):
    schedules = snapshot["teams"][0]["schedules"]
    schedules.append({"id": "s3", "name": "Slot 3", "timezone": "UTC"})
    service.run(source.id)
    ids = {item["id"]: binding(source, "rotation", item["id"]).local_id for item in schedules}
    before = rotation_state()
    shift = Shift.get().__data__.copy()
    for item, name in zip(schedules, ["Slot 2", "Slot 3", "Slot 1"], strict=True):
        item["name"] = name
    if reverse_order:
        schedules.reverse()
    preview = service.run(source.id, mode="preview")
    assert rotation_state() == before
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    assert Shift.get().__data__ == shift
    for item in schedules:
        assert binding(source, "rotation", item["id"]).local_id == ids[item["id"]]
        assert Rotation.get_by_id(ids[item["id"]]).name == item["name"]
    assert service.run(source.id)["changes"] == []


def test_new_schedule_can_take_a_name_vacated_in_same_import(source, fetched, snapshot):
    service.run(source.id)
    old_id = binding(source, "rotation", "s1").local_id
    schedules = snapshot["teams"][0]["schedules"]
    schedules[0]["name"] = "Renamed"
    schedules.insert(0, {"id": "new", "name": "Slot 1", "timezone": "UTC"})
    apply_preview(source)
    assert Rotation.get_by_id(old_id).name == "Renamed"
    assert binding(source, "rotation", "s1").local_id == old_id
    assert Rotation.get_by_id(binding(source, "rotation", "new").local_id).name == "Slot 1"
    assert service.run(source.id)["changes"] == []


@pytest.mark.parametrize("delete_missing", [False, True])
def test_removed_schedule_name_is_reusable_only_when_deletion_is_enabled(
    source, fetched, snapshot, delete_missing,
):
    source.config["delete_missing"] = delete_missing
    source.save()
    service.run(source.id)
    removed_id = binding(source, "rotation", "s1").local_id
    retained_id = binding(source, "rotation", "s2").local_id
    before = rotation_state()
    team = snapshot["teams"][0]
    team["schedules"].pop(0)
    team["schedules"][0]["name"] = "Slot 1"
    team["shifts"] = []
    if not delete_missing:
        with pytest.raises(SyncError, match="Rotation name conflict"):
            service.run(source.id, mode="preview")
        assert rotation_state() == before
        return
    preview = service.run(source.id, mode="preview")
    assert rotation_state() == before
    assert binding(source, "rotation", "s1").present
    assert any(item["kind"] == "rotation" and item["external_id"] == "s1"
               and item["action"] == "delete" for item in preview["changes"])
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    assert Rotation.get_by_id(removed_id).deleted
    assert not binding(source, "rotation", "s1").present
    assert binding(source, "rotation", "s2").local_id == retained_id
    assert Rotation.get_by_id(retained_id).name == "Slot 1"
    assert service.run(source.id)["changes"] == []


def test_deleted_rotation_can_be_restored_after_another_schedule_vacates_its_name(source, fetched, snapshot):
    service.run(source.id)
    original = copy.deepcopy(snapshot)
    removed_id = binding(source, "rotation", "s1").local_id
    # Match the persisted state after deleting the first slot and renumbering the second.
    Rotation.update(deleted=True, enabled=False).where(Rotation.id == removed_id).execute()
    Rotation.update(name="Slot 1").where(Rotation.id == binding(source, "rotation", "s2").local_id).execute()
    preview = apply_preview(source)
    assert Rotation.get_by_id(removed_id).deleted is False
    assert Rotation.get_by_id(removed_id).name == "Slot 1"
    assert Rotation.get_by_id(binding(source, "rotation", "s2").local_id).name == "Slot 2"
    assert snapshot == original
    assert all("directory-sync-" not in str(item) for item in preview["changes"])
    assert service.run(source.id)["changes"] == []


@pytest.mark.parametrize("new_schedule", [False, True])
def test_duplicate_upstream_names_fail_clearly_without_partial_changes(source, fetched, snapshot, new_schedule):
    service.run(source.id)
    before = rotation_state()
    schedules = snapshot["teams"][0]["schedules"]
    if new_schedule:
        schedules.append({"id": "s3", "name": "Slot 1", "timezone": "UTC"})
    else:
        schedules[1]["name"] = "Slot 1"
    with pytest.raises(SyncError, match="Schedule names are not unique.*s1.*s[23]"):
        service.run(source.id, mode="preview")
    assert rotation_state() == before


def test_conflicting_local_rotation_is_not_adopted_or_overwritten(source, fetched, snapshot):
    service.run(source.id)
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    local = Rotation.create(team=rotation.team_id, name="Local", start_at=rotation.start_at)
    before = rotation_state()
    snapshot["teams"][0]["schedules"][0]["name"] = local.name
    with pytest.raises(SyncError, match=rf"Rotation name conflict.*rotation {local.id}.*retained source"):
        service.run(source.id, mode="preview")
    assert rotation_state() == before


@pytest.mark.parametrize("remove_schedule", [False, True])
def test_failure_after_rename_rolls_back_names_and_deletions(source, fetched, snapshot, monkeypatch, remove_schedule):
    source.config["delete_missing"] = remove_schedule
    source.save()
    service.run(source.id)
    before = rotation_state()
    before_shift = Shift.get().__data__.copy()
    schedules = snapshot["teams"][0]["schedules"]
    shift = copy.deepcopy(snapshot["teams"][0]["shifts"][0])
    shift["id"] = "new-shift"
    if remove_schedule:
        schedules.pop(0)
        schedules[0]["name"] = "Slot 1"
        shift["schedule_id"] = "s2"
        snapshot["teams"][0]["shifts"] = [shift]
    else:
        schedules[0]["name"], schedules[1]["name"] = schedules[1]["name"], schedules[0]["name"]
        snapshot["teams"][0]["shifts"].append(shift)

    def fail(**_kwargs):
        raise SyncError("Shift write failed")

    monkeypatch.setattr(Shift, "create", fail)
    with pytest.raises(SyncError, match="Shift write failed"):
        service.run(source.id)
    assert rotation_state() == before
    assert Shift.get().__data__ == before_shift
    assert binding(source, "rotation", "s1").present


def test_local_change_after_preview_requires_new_preview(source, fetched, snapshot):
    service.run(source.id)
    schedules = snapshot["teams"][0]["schedules"]
    schedules[0]["name"], schedules[1]["name"] = schedules[1]["name"], schedules[0]["name"]
    preview = service.run(source.id, mode="preview")
    Rotation.update(name="Local edit").where(Rotation.id == binding(source, "rotation", "s1").local_id).execute()
    before = rotation_state()
    with pytest.raises(SyncError, match="Local data changed since preview"):
        service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    assert rotation_state() == before
