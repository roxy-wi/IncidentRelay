"""Source removal preserves explicit ownership and scheduler boundaries."""

from datetime import timedelta

import pytest

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db.models import (
    DirectorySyncBinding as Binding, DirectorySyncCurrent as Current,
    DirectorySyncShift as Shift, DirectorySyncSource as Source,
    Rotation, Team, User,
)
from app.services.directory_sync import management, service
from app.services.directory_sync.config import SyncBusy, SyncError
from app.services.directory_sync.runtime import readonly, source_for, sync_managed_groups
from app.services.oncall import get_current_oncall_user
from tests.factories import create_group, create_team, create_user
from tests.integrations.test_directory_sync import binding, fetched, snapshot, source  # noqa: F401

URL = "/api/admin/directory-sync"


def remove(client, headers, source, action="keep", **payload):
    return client.delete(f"{URL}/{source.id}", headers=headers,
                         json={"revision": source.revision, "data_action": action, **payload})


def test_keep_data_becomes_editable_local_schedule(client, admin_headers, source, fetched):
    service.run(source.id)
    service.run(source.id, mode="preview")
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    user_id = binding(source, "user", "u1").local_id
    team_id = rotation.team_id
    shifts = list(Shift.select().dicts())
    assert readonly("team", team_id)
    assert get_current_oncall_user(rotation) is None  # No authoritative answer yet.

    response = remove(client, admin_headers, source)
    assert response.status_code == 200
    assert response.json == {"id": source.id, "deleted": True}
    archived = Source.get_by_id(source.id)
    assert archived.deleted and archived.deleted_at
    assert not archived.enabled
    assert archived.headers_encrypted is None
    assert archived.preview_encrypted is None
    assert archived.preview_token is None
    assert archived.preview_result is None
    assert archived.approved_revision is None
    assert not Current.select().exists()
    assert list(Shift.select().dicts()) == shifts
    assert not Team.get_by_id(team_id).deleted
    assert not Rotation.get_by_id(rotation.id).deleted
    assert not readonly("team", team_id)
    assert not readonly("rotation", rotation.id)
    assert not readonly("user", user_id)
    assert not sync_managed_groups(user_id)
    assert source_for("team", team_id) is None
    assert source_for("rotation", rotation.id).id == source.id
    assert get_current_oncall_user(rotation).username == "second"  # Saved replacement wins.
    assert client.get(f"/api/rotations/{rotation.id}/imported-shifts", headers=admin_headers).status_code == 200
    shift = Shift.get()
    response = client.put(f"/api/rotations/imported-shifts/{shift.id}", headers=admin_headers, json={
        "user_id": shift.user_id, "start": shift.starts_at.isoformat() + "Z", "end": shift.ends_at.isoformat() + "Z",
        "title": "Locally managed shift", "replacements": [],
    })
    assert response.status_code == 200
    assert Shift.get_by_id(shift.id).title == "Locally managed shift"
    assert client.get(URL, headers=admin_headers).json == []
    assert client.get(f"{URL}/{source.id}", headers=admin_headers).status_code == 404
    for action in ("preview", "apply", "run", "sample"):
        assert client.post(f"{URL}/{source.id}/{action}", headers=admin_headers,
                           json={"revision": archived.revision}).status_code == 404
    assert service.process_due_sources() == 0
    assert service.process_due_current() == 0
    with pytest.raises(SyncBusy):
        service.run(source.id)


@pytest.mark.parametrize("existing_team", [True, False])
def test_delete_data_only_removes_source_created_resources(client, admin_headers, source, fetched, existing_team):
    unrelated = create_team(group=source.group, name="Unrelated")
    if existing_team:
        create_team(group=source.group, name="Platform")
        source.config["overwrite_existing"] = True
        source.save()
    service.run(source.id)
    team_id = binding(source, "team", "t1").local_id
    rotation_ids = [row.id for row in Rotation.select().where(Rotation.team == team_id)]
    user_ids = [row.id for row in User.select()]
    response = remove(client, admin_headers, source, "delete")
    assert response.status_code == 200
    assert Team.get_by_id(team_id).deleted is not existing_team
    assert not Team.get_by_id(unrelated.id).deleted
    assert all(Rotation.get_by_id(key).deleted for key in rotation_ids)
    assert not Binding.select().where(Binding.source == source.id).exists()
    assert not Shift.select().where(Shift.source == source.id).exists()
    assert [row.id for row in User.select().where(User.deleted == False)] == user_ids


@pytest.mark.parametrize("action", ["keep", "delete"])
def test_repeated_removal_is_idempotent(client, admin_headers, source, fetched, action):
    service.run(source.id)
    assert remove(client, admin_headers, source, action).status_code == 200
    revision = Source.get_by_id(source.id).revision
    remaining_shifts = Shift.select().count()
    # A retry cannot reinterpret the first choice and remove retained data.
    assert remove(client, admin_headers, source, "delete").status_code == 200
    assert Source.get_by_id(source.id).revision == revision
    assert Shift.select().count() == remaining_shifts


@pytest.mark.parametrize("action", ["keep", "delete"])
def test_removed_source_name_and_url_can_be_reused(client, admin_headers, source, fetched, action):
    service.run(source.id)
    assert remove(client, admin_headers, source, action).status_code == 200
    response = client.post(URL, headers=admin_headers, json={
        "name": source.name, "group_id": source.group_id, "config": source.config,
        "headers": {"Authorization": "PAT replacement-secret"}, "enabled": False,
    })
    assert response.status_code == 201
    created = response.json
    assert created["id"] != source.id
    assert created["name"] == source.name
    assert created["config"]["base_url"] == source.config["base_url"]
    assert not created["approved"]
    assert not created["enabled"]
    assert created["has_headers"]
    assert "replacement-secret" not in response.get_data(as_text=True)
    assert [item["id"] for item in client.get(URL, headers=admin_headers).json] == [created["id"]]
    preview = service.run(created["id"], mode="preview")
    service.run(created["id"], mode="apply", preview_token=preview["preview_token"])
    assert Source.get_by_id(created["id"]).approved_revision == created["revision"]
    assert Team.select().where(Team.deleted == False).count() == 1


@pytest.mark.parametrize("state", ["pending", "full", "current"])
@pytest.mark.parametrize("action", ["keep", "delete"])
def test_busy_source_cannot_be_removed(client, admin_headers, source, state, action):
    if state == "pending":
        source.pending_mode = "preview"
    else:
        prefix = "current_" if state == "current" else ""
        setattr(source, prefix + "lease", "worker")
        setattr(source, prefix + "lease_until", utc_now() + timedelta(minutes=1))
    source.save()
    assert remove(client, admin_headers, source, action).status_code == 409
    assert not Source.get_by_id(source.id).deleted


def test_removal_fences_an_expired_worker(client, admin_headers, source):
    source.lease = "old-worker"
    source.lease_until = utc_now() - timedelta(seconds=1)
    source.save()
    assert remove(client, admin_headers, source).status_code == 200
    with pytest.raises(SyncError):
        service.heartbeat(source.id, "old-worker")
    assert Source.get_by_id(source.id).lease is None


@pytest.mark.parametrize("payload", [None, {}, [], {"revision": 1}, {"revision": True, "data_action": "keep"},
                                    {"revision": 1, "data_action": "all"},
                                    {"revision": 1, "data_action": "keep", "force": True}])
def test_removal_requires_explicit_valid_choice(client, admin_headers, source, payload):
    assert client.delete(f"{URL}/{source.id}", headers=admin_headers, json=payload).status_code == 400
    assert not Source.get_by_id(source.id).deleted


def test_stale_removal_does_not_touch_data(client, admin_headers, source, fetched):
    service.run(source.id)
    assert remove(client, admin_headers, source, "delete", revision=source.revision + 1).status_code == 409
    assert not Source.get_by_id(source.id).deleted
    assert not Team.get().deleted
    assert Shift.select().count() == 1


@pytest.mark.parametrize("role", ["user_admin", "viewer"])
def test_removal_requires_destination_group_admin(client, source, role):
    actor = create_user(group=create_group() if role == "user_admin" else source.group, group_role=role)
    headers = {"Authorization": "Bearer " + create_access_token(actor)[0]}
    assert remove(client, headers, source).status_code == 403
    assert not Source.get_by_id(source.id).deleted


def test_removal_requires_write_token_scope(client, source, admin_user):
    from tests.integrations.test_admin_api_tokens import personal_token
    _, headers = personal_token(admin_user, ["directory-sync:read"], group_id=source.group_id)
    assert remove(client, headers, source).status_code == 403
    _, headers = personal_token(admin_user, ["directory-sync:write"], group_id=source.group_id)
    assert remove(client, headers, source).status_code == 200


def test_deletion_rolls_back_resource_cleanup_on_failure(client, admin_headers, source, fetched, monkeypatch):
    service.run(source.id)
    attempted = []

    def failure(rotation_id):
        attempted.append(rotation_id)
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(management.rotations_repo, "soft_delete_rotation", failure)
    response = remove(client, admin_headers, source, "delete")
    assert response.status_code == 500
    assert attempted
    assert not Source.get_by_id(source.id).deleted
    assert not Team.get().deleted
    assert not Rotation.select().where(Rotation.deleted == True).exists()
    assert Shift.select().count() == 1


def test_source_cannot_delete_a_team_moved_to_another_group(client, admin_headers, source, fetched):
    service.run(source.id)
    team = Team.get()
    team.group = create_group()
    team.save()
    assert remove(client, admin_headers, source, "delete").status_code == 409
    assert not Team.get_by_id(team.id).deleted
    assert not Source.get_by_id(source.id).deleted


@pytest.mark.parametrize("current", [False, True])
def test_scheduler_rechecks_pause_after_reading_due_source(source, fetched, monkeypatch, current):
    service.run(source.id)
    now = utc_now()
    Source.update(enabled=True, last_current_at=now, next_run_at=now, next_current_at=now).where(Source.id == source.id).execute()
    original_claim = service.claim

    def pause_before_claim(source_id, **kwargs):
        assert kwargs["scheduled"]
        Source.update(enabled=False).where(Source.id == source_id).execute()
        return original_claim(source_id, **kwargs)

    def unexpected_fetch(*_args):
        pytest.fail("Paused work must not issue an API request")

    monkeypatch.setattr(service, "claim", pause_before_claim)
    monkeypatch.setattr(service, "fetch_current" if current else "fetch_snapshot", unexpected_fetch)
    process = service.process_due_current if current else service.process_due_sources
    assert process() == 0
    assert not Source.get_by_id(source.id).enabled


def test_openapi_describes_explicit_removal_choice():
    from app.api.openapi.spec import build_openapi_spec
    operation = build_openapi_spec()["paths"][URL + "/{source_id}"]["delete"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert set(schema["required"]) == {"revision", "data_action"}
    assert schema["properties"]["data_action"]["enum"] == ["keep", "delete"]
