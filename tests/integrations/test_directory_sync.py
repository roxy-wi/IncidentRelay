"""End-to-end synchronization contracts, failure isolation and access boundaries."""

import copy
import json
from datetime import timedelta

import pytest

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.crypto import decrypt_json, encrypt_json
from app.modules.db.models import (
    DirectorySyncBinding as Binding, DirectorySyncCurrent as Current,
    DirectorySyncShift as Shift, DirectorySyncSource as Source,
    Rotation, SsoIdentity, SsoProvider, Team, TeamUser, User, UserGroup,
)
from app.services.directory_sync import client as client_module, service
from app.services.directory_sync.client import ApiClient
from app.services.directory_sync.config import SyncBusy, SyncConfig, SyncError, org_service_preset
from app.services.directory_sync.fetch import fetch_snapshot, iso, window
from app.services.directory_sync.runtime import imported_candidates
from app.services.oncall import get_current_oncall_user
from tests.factories import create_group, create_team, create_user

URL = "/api/admin/directory-sync"


@pytest.fixture
def source(admin_user):
    return Source.create(name="OnCall", group=create_group(), created_by=admin_user,
                         config=org_service_preset(), headers_encrypted=encrypt_json({"Authorization": "PAT secret-test"}))


@pytest.fixture
def snapshot():
    now = utc_now()
    return {**window(SyncConfig.model_validate(org_service_preset())),
            "users": [{"id": "u1", "username": "first", "name": "First", "email": "first@example.com", "inactive": False},
                      {"id": "u2", "username": "second", "name": "Second", "email": "second@example.com", "inactive": False}],
            "teams": [{"id": "t1", "name": "Platform", "description": "External team", "enabled": True,
                       "members": ["u1"], "responsible": "u1",
                       "schedules": [{"id": "s1", "name": "Slot 1", "timezone": "Europe/Moscow"},
                                     {"id": "s2", "name": "Slot 2", "timezone": "Europe/Moscow"}],
                       "shifts": [{"id": "shift1", "schedule_id": "s1", "user_id": "u1", "start": iso(now - timedelta(hours=2)),
                                   "end": iso(now + timedelta(hours=2)), "unavailable": False,
                                   "replacements": [{"id": "rep1", "user_id": "u2", "start": iso(now - timedelta(hours=1)),
                                                     "end": iso(now + timedelta(hours=1)), "precedence": 2, "inactive": False}]}]}]}


@pytest.fixture
def fetched(monkeypatch, snapshot):
    monkeypatch.setattr(service, "fetch_snapshot", lambda _client: copy.deepcopy(snapshot))
    return snapshot


def binding(source, kind, key):
    return Binding.get(Binding.source == source.id, Binding.kind == kind, Binding.external_id == key)


def test_preview_apply_is_atomic_idempotent_and_keeps_password_empty(source, fetched):
    before = User.select().count()
    preview = service.run(source.id, mode="preview")
    assert User.select().count() == before
    assert not Team.select().exists()
    assert not Shift.select().exists()
    assert any(c["kind"] == "rotation" for c in preview["changes"])
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    assert Rotation.select().count() == 2
    assert User.get(User.email == "first@example.com").password_hash is None
    # A replacement outside the roster has a user, but is not silently made a team member.
    second = User.get(User.email == "second@example.com")
    assert not TeamUser.select().where(TeamUser.user == second.id).exists()
    assert service.run(source.id)["changes"] == []


def test_changed_preview_and_expired_preview_are_rejected(source, fetched):
    preview = service.run(source.id, mode="preview")
    create_user(email="first@example.com", username="different")
    with pytest.raises(SyncError, match="Local data changed"):
        service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    assert not Team.select().exists()
    Source.update(preview_until=utc_now() - timedelta(seconds=1)).where(Source.id == source.id).execute()
    with pytest.raises(SyncError, match="expired"):
        service.run(source.id, mode="apply", preview_token=preview["preview_token"])


def test_failed_fetch_never_removes_data(source, fetched, monkeypatch):
    source.config["delete_missing"] = True
    source.save()
    service.run(source.id)
    def failure(_client):
        raise SyncError("shifts: API returned HTTP 504")
    monkeypatch.setattr(service, "fetch_snapshot", failure)
    with pytest.raises(SyncError):
        service.run(source.id)
    assert Shift.select().count() == 1
    assert not Team.get_by_id(binding(source, "team", "t1").local_id).deleted
    assert Source.get_by_id(source.id).last_error


def test_delete_is_window_bounded_and_accounts_survive(source, fetched):
    source.config["delete_missing"] = True
    source.save()
    service.run(source.id)
    shift = Shift.get()
    Shift.create(source=source, rotation=shift.rotation, external_id="history", user=shift.user,
                 starts_at=utc_now() - timedelta(days=800), ends_at=utc_now() - timedelta(days=799))
    fetched["teams"][0]["shifts"] = []
    service.run(source.id)
    assert [row.external_id for row in Shift.select()] == ["history"]
    fetched["teams"] = []
    fetched["users"] = []
    service.run(source.id)
    assert Team.get().deleted
    assert all(row.deleted for row in Rotation.select())
    assert not User.get(User.email == "first@example.com").deleted
    assert not UserGroup.get(UserGroup.user == binding(source, "user", "u1").local_id).active


def test_keep_missing_preserves_local_data(source, fetched):
    service.run(source.id)
    fetched["teams"] = []
    fetched["users"] = []
    service.run(source.id)
    assert not Team.get().deleted
    assert Shift.select().count() == 1


def test_existing_team_skip_then_explicit_adoption(source, fetched):
    existing = create_team(group=source.group, name="Platform")
    service.run(source.id)
    assert not Rotation.select().exists()
    source.config["overwrite_existing"] = True
    source.save()
    service.run(source.id)
    assert Rotation.select().count() == 2
    assert binding(source, "team", "t1").local_id == existing.id


def test_foreign_team_mapping_is_rejected_and_rolls_back_users(source, fetched):
    foreign = create_team(group=create_group())
    source.config["team_matches"] = {"t1": foreign.id}
    source.save()
    with pytest.raises(SyncError, match="destination group"):
        service.run(source.id)
    assert not User.select().where(User.email == "first@example.com").exists()


def test_duplicate_email_rejected_and_shared_profile_untouched(source, fetched):
    shared = create_user(email="FIRST@EXAMPLE.COM", group=create_group())
    shared.display_name = "Local profile"
    shared.save()
    service.run(source.id)
    assert binding(source, "user", "u1").local_id == shared.id
    assert User.get_by_id(shared.id).display_name == "Local profile"
    create_user(email="first@example.com")
    with pytest.raises(SyncError, match="Email identity conflict"):
        service.run(source.id)


def test_replacements_calendar_and_ambiguous_intervals(source, fetched):
    service.run(source.id)
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    now = utc_now()
    events = imported_candidates(rotation, now - timedelta(hours=2), now + timedelta(hours=2))
    assert [event["event"]["username"] for event in events] == ["first", "second", "first"]
    first = Shift.get()
    Shift.create(source=source, rotation=rotation, external_id="overlap", user=first.user,
                 starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(minutes=1))
    assert imported_candidates(rotation, now, now + timedelta(seconds=1)) == []


@pytest.mark.parametrize("status", ["active", "gap", "unavailable", "ambiguous"])
def test_current_cache_status_and_expiry(source, fetched, monkeypatch, status):
    service.run(source.id)
    now = utc_now()
    rows = [{"id": key, "status": status, "user_id": "u2", "valid_until": iso(now + timedelta(hours=1))} for key in ("s1", "s2")]
    monkeypatch.setattr(service, "fetch_current", lambda *_args: rows)
    service.refresh_current(source.id)
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    user = get_current_oncall_user(rotation)
    assert (user.username if user else None) == ("second" if status == "active" else None)
    assert Current.get(Current.rotation == rotation.id).valid_until <= utc_now() + timedelta(seconds=120)
    Current.update(valid_until=utc_now() - timedelta(seconds=1)).execute()
    assert get_current_oncall_user(rotation) is None


def test_current_refresh_is_independent_of_full_sync_lease(source, fetched, monkeypatch):
    service.run(source.id)
    token = service.claim(source.id)
    monkeypatch.setattr(service, "fetch_current", lambda *_args: [])
    service.refresh_current(source.id)
    with pytest.raises(SyncBusy):
        service.run(source.id)
    Source.update(lease_until=utc_now() - timedelta(seconds=1)).where(Source.id == source.id).execute()
    with pytest.raises(SyncError, match="expired"):
        service.heartbeat(source.id, token)


def test_api_queue_permissions_and_encrypted_headers(client, admin_headers, source, fetched):
    result = client.get(f"{URL}/{source.id}", headers=admin_headers)
    assert result.status_code == 200
    assert "secret-test" not in result.text
    response = client.post(f"{URL}/{source.id}/preview", headers=admin_headers, json={"revision": 1})
    assert response.status_code == 202
    service.process_due_sources()
    source = Source.get_by_id(source.id)
    assert source.preview_token and not source.pending_mode
    assert decrypt_json(source.preview_encrypted)["snapshot"]["teams"]
    response = client.post(f"{URL}/{source.id}/apply", headers=admin_headers,
                           json={"revision": 1, "preview_token": source.preview_token})
    assert response.status_code == 202
    service.process_due_sources()
    assert Rotation.select().count() == 2
    stranger = create_user(group=create_group(), group_role="user_admin")
    headers = {"Authorization": "Bearer " + create_access_token(stranger)[0]}
    assert client.get(f"{URL}/{source.id}", headers=headers).status_code == 403
    assert client.get(URL, headers=headers).json == []


def test_readonly_enforced_on_existing_apis(client, admin_headers, source, fetched):
    service.run(source.id)
    team = binding(source, "team", "t1").local_id
    rotation = binding(source, "rotation", "s1").local_id
    user = binding(source, "user", "u1").local_id
    assert client.delete(f"/api/teams/{team}", headers=admin_headers).status_code == 409
    assert client.delete(f"/api/rotations/{rotation}", headers=admin_headers).status_code == 409
    assert client.delete(f"/api/admin/users/{user}", headers=admin_headers).status_code == 409
    source.config["editable"] = True
    source.save()
    assert client.delete(f"/api/rotations/{rotation}", headers=admin_headers).status_code == 200


def test_email_linking_reuses_imported_user_without_oidc_autocreate(source, fetched):
    from app.modules.sso.sso_login import _resolve_sso_user
    service.run(source.id)
    provider = SsoProvider.create(label="OIDC", slug="test-oidc", enabled=True, protocol="oidc", auto_create_users=False)
    user = _resolve_sso_user(provider, {"sub": "oidc-subject", "email": "FIRST@example.com", "email_verified": True})
    assert user.id == binding(source, "user", "u1").local_id
    assert SsoIdentity.get().subject == "oidc-subject"


def test_http_pagination_and_post_body_preserve_types(monkeypatch):
    config = SyncConfig.model_validate(org_service_preset())
    calls = []
    def transport(url, **kwargs):
        calls.append((url, kwargs))
        if "batch-current" in url:
            assert json.loads(kwargs["body"]) == {"scheduleUuids": ["s1", "s2"]}
            return 200, {}, b'{"duties": []}'
        return (200, {}, b'{"teams": [{"name": "first"}], "nextPageToken": "next"}') if len(calls) == 1 else (200, {}, b'{"teams": [{"name": "second"}], "nextPageToken": ""}')
    monkeypatch.setattr(client_module, "_request_once", transport)
    api = ApiClient(config, {"Authorization": "PAT hidden"})
    assert len(api.records("teams", {})) == 2
    assert "pageToken=next" in calls[1][0]
    api.records("current", {"schedule_ids": ["s1", "s2"]})
    assert "hidden" not in json.dumps(api.samples)


@pytest.mark.parametrize("body", [b'{"teams": null}', b'{"error": "bad"}', b'not json'])
def test_invalid_api_shape_is_not_an_empty_snapshot(monkeypatch, body):
    monkeypatch.setattr(client_module, "_request_once", lambda *_args, **_kwargs: (200, {}, body))
    with pytest.raises(SyncError):
        fetch_snapshot(ApiClient(SyncConfig.model_validate(org_service_preset()), {}))


def test_repeated_cursor_and_http_errors_do_not_expose_secrets(monkeypatch):
    config = SyncConfig.model_validate(org_service_preset())
    monkeypatch.setattr(client_module, "_request_once", lambda *_args, **_kwargs: (200, {}, b'{"teams": [], "nextPageToken": "repeat"}'))
    with pytest.raises(SyncError, match="repeated"):
        ApiClient(config, {}).records("teams", {})
    monkeypatch.setattr(client_module, "_request_once", lambda *_args, **_kwargs: (403, {}, b'{"secret": "never-log-me"}'))
    with pytest.raises(SyncError, match="HTTP 403") as failure:
        ApiClient(config, {}).records("teams", {})
    assert "never-log-me" not in str(failure.value)


def test_full_org_contract_fetches_outside_roster_users(monkeypatch):
    config = SyncConfig.model_validate(org_service_preset())
    now = utc_now()
    def transport(url, **kwargs):
        if "support-team-catalog" in url:
            data = {"teams": [{"enrolledScopeUuid": "t1", "name": "Platform"}, {"name": "Not enrolled"}], "nextPageToken": ""}
        elif "/employees" in url:
            from urllib.parse import parse_qs, urlsplit
            key = parse_qs(urlsplit(url).query)["uuid"][0]
            data = {"employees": [{"uuid": key, "username": key, "email": key + "@example.com", "firstname": "Person", "lastname": key}]}
        elif "/shifts" in url:
            data = {"shifts": [{"uuid": "shift", "scheduleUuid": "s1", "employee": {"employeeUuid": "member", "inactive": False},
                                "startAt": iso(now - timedelta(hours=1)), "endAt": iso(now + timedelta(hours=1)),
                                "availabilityConflict": False, "recurrence": {"frequency": "DUTY_FREQUENCY_WEEK"},
                                "replacements": [{"uuid": "replacement", "employee": {"employeeUuid": "outside", "inactive": False},
                                                  "startAt": iso(now), "endAt": iso(now + timedelta(minutes=30)), "precedence": "2"}]}]}
        else:
            data = {"name": "Platform", "enabled": True, "responsible": {"employeeUuid": "leader"},
                    "roster": [{"person": {"employeeUuid": "member", "username": "member", "inactive": False}}],
                    "schedules": [{"uuid": "s1", "timezone": "Europe/Moscow"}]}
        return 200, {}, json.dumps(data).encode()
    monkeypatch.setattr(client_module, "_request_once", transport)
    result = fetch_snapshot(ApiClient(config, {}))
    assert len(result["teams"]) == 1
    assert {user["id"] for user in result["users"]} == {"member", "leader", "outside"}
    assert len(result["teams"][0]["shifts"]) == 1
    assert result["teams"][0]["shifts"][0]["replacements"][0]["precedence"] == 2


def test_generic_mapping_and_bulk_people(monkeypatch):
    data = org_service_preset()
    data["user_fetch"] = "all"
    data["operations"] = {
        "teams": {"path": "/departments", "items": "result"},
        "user": {"path": "/directory", "items": "people"},
        "shifts": {"path": "/assignments/{team_id}", "items": "records"},
    }
    data.update(team_filter=None, team_fields={"id": "key", "name": "label"},
                members={"path": "people", "fields": {"id": "key"}}, responsible=None,
                schedules={"path": "slots", "fields": {"id": "key", "timezone": {"value": "UTC"}}},
                user_fields={"id": "key", "email": "mail", "inactive": {"path": "state", "values": {"enabled": False, "disabled": True}}})
    responses = {"departments": {"result": [{"key": "dept", "label": "Custom", "people": [{"key": "person"}], "slots": [{"key": "slot"}]}]},
                 "directory": {"people": [{"key": "person", "mail": "person@example.com", "state": "enabled"}]},
                 "dept": {"records": []}}
    monkeypatch.setattr(client_module, "_request_once", lambda url, **_kwargs: (200, {}, json.dumps(responses[url.rsplit("/", 1)[-1]]).encode()))
    result = fetch_snapshot(ApiClient(SyncConfig.model_validate(data), {}))
    assert result["users"][0]["inactive"] is False
    assert result["teams"][0]["schedules"][0]["timezone"] == "UTC"


def test_owner_revocation_during_fetch_prevents_commit(source, fetched, monkeypatch):
    manager = create_user(group=source.group, group_role="user_admin")
    source.created_by = manager
    source.save()
    def fetch(_client):
        UserGroup.update(active=False).where(UserGroup.user == manager.id).execute()
        return fetched
    monkeypatch.setattr(service, "fetch_snapshot", fetch)
    with pytest.raises(SyncError, match="no longer administers"):
        service.run(source.id)
    assert not Team.select().exists()


def test_api_owned_memberships_are_not_removed_or_demoted_by_oidc(source, fetched):
    from app.modules.sso.sso_login import _sync_group_memberships
    from app.modules.db.models import SsoGroupMapping
    service.run(source.id)
    user = User.get_by_id(binding(source, "user", "u1").local_id)
    provider = SsoProvider.create(label="SSO", slug="authority", enabled=True, remove_missing_group_memberships=True)
    SsoGroupMapping.create(provider=provider, external_group="missing", incidentrelay_group=source.group, group_role="editor")
    _sync_group_memberships(user, provider, {"groups": []})
    membership = UserGroup.get(UserGroup.user == user.id, UserGroup.group == source.group_id)
    assert membership.active and membership.role == "viewer"


def test_changed_config_must_be_previewed_before_enabling(client, admin_headers, source, fetched):
    service.run(source.id)
    config = copy.deepcopy(source.config)
    config["delete_missing"] = True
    response = client.put(f"{URL}/{source.id}", headers=admin_headers,
                          json={"name": source.name, "group_id": source.group_id, "config": config, "revision": 1})
    assert response.status_code == 200
    assert not response.json["approved"]
    response = client.put(f"{URL}/{source.id}", headers=admin_headers,
                          json={"name": source.name, "group_id": source.group_id, "config": config, "revision": 2, "enabled": True})
    assert response.status_code == 409


def test_editable_imported_shifts_use_existing_rotation_access(client, admin_headers, source, fetched):
    source.config["editable"] = True
    source.save()
    service.run(source.id)
    shift = Shift.get()
    response = client.get(f"/api/rotations/{shift.rotation_id}/imported-shifts", headers=admin_headers)
    assert response.status_code == 200 and response.json["items"][0]["id"] == shift.id
    now = utc_now()
    body = {"user_id": binding(source, "user", "u2").local_id, "start": iso(now - timedelta(hours=1)),
            "end": iso(now + timedelta(hours=1)), "title": "Local edit", "replacements": []}
    assert client.put(f"/api/rotations/imported-shifts/{shift.id}", headers=admin_headers, json=body).status_code == 200
    assert get_current_oncall_user(shift.rotation).username == "second"
    assert client.delete(f"/api/rotations/imported-shifts/{shift.id}", headers=admin_headers).status_code == 200
    assert get_current_oncall_user(shift.rotation) is None
    service.run(source.id)
    assert not Shift.get().deleted and not Shift.get().local_override


def test_personal_token_scopes_and_group_bounds(client, source, admin_user):
    from tests.integrations.test_admin_api_tokens import personal_token
    _, headers = personal_token(admin_user, ["directory-sync:read"], group_id=source.group_id)
    assert client.get(URL, headers=headers).status_code == 200
    assert client.post(f"{URL}/{source.id}/preview", headers=headers, json={"revision": 1}).status_code == 403
    _, headers = personal_token(admin_user, ["directory-sync:read"], group_id=create_group().id)
    assert client.get(URL, headers=headers).json == []
    assert client.get(f"{URL}/{source.id}", headers=headers).status_code == 403


def test_openapi_includes_config_and_queue_contract():
    from app.api.openapi.spec import build_openapi_spec
    spec = build_openapi_spec()
    assert "202" in spec["paths"][URL + "/{source_id}/preview"]["post"]["responses"]
    assert "operations" in spec["components"]["schemas"]["DirectorySyncConfig"]["properties"]


def test_readonly_preserves_authorization_and_personal_preferences(client, admin_headers, source, fetched):
    service.run(source.id)
    team_id = binding(source, "team", "t1").local_id
    stranger = create_user(group=create_group(), group_role="user_admin")
    headers = {"Authorization": "Bearer " + create_access_token(stranger)[0]}
    assert client.delete(f"/api/teams/{team_id}", headers=headers).status_code == 403
    user = User.get_by_id(binding(source, "user", "u1").local_id)
    headers = {"Authorization": "Bearer " + create_access_token(user)[0]}
    assert client.put("/api/profile", headers=headers, json={"email": "changed@example.com"}).status_code == 409
    assert client.put("/api/profile", headers=headers, json={"locale": "ru"}).status_code == 200
    assert client.post(f"/api/groups/{source.group_id}/users", headers=admin_headers,
                       json={"user_id": user.id, "role": "editor", "active": True}).status_code == 409
    assert client.post(f"/api/groups/{source.group_id}/users", headers=admin_headers,
                       json={"user_id": str(user.id), "role": "editor", "active": True}).status_code == 409


def test_oidc_does_not_overwrite_api_team_role_in_existing_group(source, fetched):
    from app.modules.sso.sso_login import _sync_group_memberships
    from app.modules.db.models import SsoGroupMapping
    user = create_user(email="first@example.com", group=source.group, group_role="viewer")
    service.run(source.id)
    team_id = binding(source, "team", "t1").local_id
    provider = SsoProvider.create(label="SSO", slug="team-authority", enabled=True)
    SsoGroupMapping.create(provider=provider, external_group="matching", incidentrelay_group=source.group,
                           incidentrelay_team=team_id, group_role="viewer", team_role="viewer")
    _sync_group_memberships(user, provider, {"groups": ["matching"]})
    assert TeamUser.get(TeamUser.user == user.id, TeamUser.team == team_id).role == "manager"


def test_preview_can_restore_source_deleted_objects(source, fetched):
    source.config["delete_missing"] = True
    source.save()
    service.run(source.id)
    original = copy.deepcopy(fetched)
    fetched.update(teams=[], users=[])
    service.run(source.id)
    assert Team.get().deleted_at is not None
    fetched.update(original)
    preview = service.run(source.id, mode="preview")
    assert Team.get().deleted
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    assert not Team.get().deleted
    assert all(not row.deleted for row in Rotation.select())


def test_moving_local_shift_suppresses_old_authoritative_assignment(client, admin_headers, source, fetched, monkeypatch):
    source.config["editable"] = True
    source.save()
    service.run(source.id)
    monkeypatch.setattr(service, "fetch_current", lambda *_args: [
        {"id": key, "status": "active", "user_id": "u1", "valid_until": iso(utc_now() + timedelta(minutes=2))}
        for key in ("s1", "s2")
    ])
    service.refresh_current(source.id)
    shift = Shift.get()
    assert get_current_oncall_user(shift.rotation).username == "first"
    body = {"user_id": shift.user_id, "start": iso(utc_now() + timedelta(days=1)),
            "end": iso(utc_now() + timedelta(days=2)), "replacements": []}
    assert client.put(f"/api/rotations/imported-shifts/{shift.id}", headers=admin_headers, json=body).status_code == 200
    assert get_current_oncall_user(shift.rotation) is None


def test_current_unknown_person_keeps_cache_and_requests_full_refresh(source, fetched, monkeypatch):
    service.run(source.id)
    rows = [{"id": key, "status": "active", "user_id": "u1", "valid_until": iso(utc_now() + timedelta(minutes=2))}
            for key in ("s1", "s2")]
    monkeypatch.setattr(service, "fetch_current", lambda *_args: rows)
    service.refresh_current(source.id)
    previous = list(Current.select().dicts())
    rows[1]["user_id"] = "new-person"
    with pytest.raises(SyncError, match="new person"):
        service.refresh_current(source.id)
    assert list(Current.select().dicts()) == previous
    assert Source.get_by_id(source.id).next_run_at <= utc_now()


def test_concurrent_workers_only_one_claims_source(source, db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    def worker():
        with db.connection_context():
            barrier.wait(timeout=10)
            try:
                return service.claim(source.id)
            except SyncBusy:
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sum(value is not None for value in results) == 1
    assert Source.get_by_id(source.id).lease in results


def test_concurrent_sources_deduplicate_shared_email(source, snapshot, monkeypatch, db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    second = Source.create(name="Other group", group=create_group(), created_by=source.created_by,
                           config=source.config, headers_encrypted=encrypt_json({}))
    barrier = Barrier(2)
    def fetch(_client):
        barrier.wait(timeout=10)
        return copy.deepcopy(snapshot)
    monkeypatch.setattr(service, "fetch_snapshot", fetch)
    def worker(source_id):
        with db.connection_context():
            return service.run(source_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [source.id, second.id]))
    assert len(results) == 2
    assert User.select().where(User.email == "first@example.com").count() == 1
    assert Team.select().count() == 2
    assert binding(source, "user", "u1").local_id == binding(second, "user", "u1").local_id


def test_queue_rejects_non_object_and_shift_missing_returns_404(client, admin_headers, source):
    assert client.post(f"{URL}/{source.id}/preview", headers=admin_headers, json=[1]).status_code == 400
    assert client.delete("/api/rotations/imported-shifts/999999", headers=admin_headers).status_code == 404


def test_api_retries_transient_failure_but_not_authorization(monkeypatch):
    calls = []
    def transport(*_args, **_kwargs):
        calls.append(True)
        return (503, {}, b"temporary") if len(calls) < 3 else (200, {}, b'{"teams": []}')
    monkeypatch.setattr(client_module, "_request_once", transport)
    monkeypatch.setattr(client_module.time, "sleep", lambda _delay: None)
    assert ApiClient(SyncConfig.model_validate(org_service_preset()), {}).records("teams", {}) == []
    assert len(calls) == 3
    calls.clear()
    def forbidden(*_args, **_kwargs):
        calls.append(True)
        return 401, {}, b"private"
    monkeypatch.setattr(client_module, "_request_once", forbidden)
    with pytest.raises(SyncError, match="401"):
        ApiClient(SyncConfig.model_validate(org_service_preset()), {}).records("teams", {})
    assert len(calls) == 1


def test_preview_plan_does_not_depend_on_worker_iteration_order():
    changes = [{"kind": "team_member", "external_id": "b", "action": "create"},
               {"kind": "team_member", "external_id": "a", "action": "create"}]
    assert service.digest(changes) == service.digest(list(reversed(changes)))
