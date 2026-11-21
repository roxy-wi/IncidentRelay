"""Resource boundaries must survive every supported token consumer."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import time

import pytest

from app.modules.common import utc_now
from app.modules.db import tokens_repo
from app.modules.db.models import (
    Alert, AlertRoute, ApiToken, PendingOrchestratedEvent, Service, Team, User,
)
from app.modules.db.orchestrations_repo import (
    create_orchestration,
    get_or_create_draft,
    replace_draft_rules,
    set_runtime_state,
)
from app.services.integrations.auth import hash_token
from tests.factories import (
    add_user_to_team, create_group, create_route, create_service, create_team,
    create_user, unique,
)
from app.services import team_management
from app.services.service_catalog import mutations as service_mutations
from app.services.orchestration.publication import publish_draft


def personal_token(user, *, group=None, team=None, scopes=None, expires_at=None):
    """Return a real credential and persisted token, never a mocked principal."""
    raw = unique("bounded-token")
    token = tokens_repo.create_token(
        name=raw, token_prefix=raw[:12], token_hash=hash_token(raw),
        scopes=scopes or ["*"], user=user.id if user else None,
        group=group.id if group else None, team=team.id if team else None,
        expires_at=expires_at,
    )
    return {"Authorization": f"Bearer {raw}"}, token


def route_token(team, *, source="webhook"):
    raw = unique("route-token")
    route = create_route(team, source=source, token_hash=hash_token(raw))
    return {"Authorization": f"Bearer {raw}"}, route


def webhook(client, headers, *, team=None, fingerprint="shared-fingerprint",
            status="firing"):
    payload = {"title": "Token isolation", "fingerprint": fingerprint,
               "status": status}
    if team:
        payload["team"] = team.slug
    return client.post("/api/integrations/webhook", json=payload, headers=headers)


def publish_pause(group, user):
    orchestration = create_orchestration(
        group_id=group.id, name=unique("pause"), scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(draft.id, [{
        "name": "Pause", "condition_tree": {},
        "actions": [{"type": "pause", "seconds": 120}],
        "processing_mode": "continue",
    }])
    publish_draft(orchestration.id, actor_id=user.id)
    return set_runtime_state(
        orchestration.id, enabled=True, mode="active", compatibility_mode="hybrid",
    )


@pytest.mark.parametrize("bound", ["group", "team"])
def test_admin_token_cannot_update_another_team(client, admin_user, db, bound):
    own_group, other_group = create_group(), create_group()
    own, other = create_team(own_group), create_team(other_group)
    headers, _ = personal_token(
        admin_user, **{bound: own_group if bound == "group" else own},
        scopes=["teams:write"],
    )
    response = client.put(f"/api/teams/{other.id}", headers=headers, json={
        "group_id": other_group.id, "slug": other.slug, "name": "Unauthorized",
    })
    assert response.status_code == 403
    assert Team.get_by_id(other.id).name == other.name
    allowed = client.put(f"/api/teams/{own.id}", headers=headers, json={
        "group_id": own_group.id, "slug": own.slug, "name": "Authorized",
    })
    assert allowed.status_code == 200
    assert Team.get_by_id(own.id).name == "Authorized"


@pytest.mark.parametrize("explicit_null", [False, True])
def test_child_token_inherits_group_and_expiry(client, admin_user, db, explicit_null):
    group = create_group()
    expiry = utc_now() + timedelta(hours=1)
    headers, _ = personal_token(
        admin_user, group=group, scopes=["profile:write", "teams:read"],
        expires_at=expiry,
    )
    payload = {"name": "child", "scopes": ["teams:read"]}
    if explicit_null:
        payload["group_id"] = None
    response = client.post("/api/profile/tokens", headers=headers, json=payload)
    assert response.status_code == 201
    child = ApiToken.get_by_id(response.get_json()["id"])
    assert child.group_id == group.id
    assert child.expires_at == expiry


def test_child_token_cannot_switch_group(client, admin_user, db):
    own, other = create_group(), create_group()
    headers, _ = personal_token(admin_user, group=own, scopes=["profile:write"])
    before = ApiToken.select().count()
    response = client.post("/api/profile/tokens", headers=headers, json={
        "name": "escape", "scopes": ["profile:write"], "group_id": other.id,
    })
    assert response.status_code == 403
    assert ApiToken.select().count() == before


@pytest.mark.parametrize("admin_owner", [False, True])
def test_personal_intake_cannot_select_foreign_team(client, db, admin_owner):
    group, other_group = create_group(), create_group()
    user = create_user(group=group, is_admin=admin_owner)
    own, other = create_team(group), create_team(other_group)
    add_user_to_team(own, user, role="responder")
    create_route(own, source="webhook")
    create_route(other, source="webhook")
    headers, _ = personal_token(user, group=group, scopes=["alerts:write"])
    denied = webhook(client, headers, team=other)
    assert denied.status_code == 403
    assert Alert.select().count() == 0
    assert webhook(client, headers, team=own).status_code == 200
    assert Alert.get().team_id == own.id


@pytest.mark.parametrize("status", ["firing", "resolved"])
def test_route_fingerprint_does_not_mutate_another_route(client, db, status):
    own, other = create_team(create_group()), create_team(create_group())
    own_headers, own_route = route_token(own)
    other_headers, other_route = route_token(other)
    assert webhook(client, other_headers).status_code == 200
    victim = Alert.get(Alert.route == other_route.id)
    victim_group_id = victim.group_id
    response = webhook(client, own_headers, status=status)
    assert response.status_code in (200, 202)
    victim = Alert.get_by_id(victim.id)
    assert victim.status == "firing"
    assert victim.route_id == other_route.id
    assert victim.team_id == other.id
    assert victim.group_id == victim_group_id
    assert victim.group.status == "firing"
    if status == "firing":
        assert Alert.select().count() == 2
        assert Alert.get(Alert.route == own_route.id).group_id != victim_group_id


@pytest.mark.parametrize("status", ["firing", "resolved"])
def test_pending_fingerprint_is_scoped_to_route(client, db, status):
    group = create_group()
    user = create_user(group=group)
    publish_pause(group, user)
    own_headers, own_route = route_token(create_team(group))
    other_headers, other_route = route_token(create_team(group))
    assert webhook(client, other_headers).status_code == 202
    victim = PendingOrchestratedEvent.get()
    assert webhook(client, own_headers, status=status).status_code == 202
    victim = PendingOrchestratedEvent.get_by_id(victim.id)
    assert victim.status == "pending"
    assert victim.route_id == other_route.id
    assert victim.active_key is not None
    if status == "firing":
        assert PendingOrchestratedEvent.select().count() == 2
        assert PendingOrchestratedEvent.get(
            PendingOrchestratedEvent.route == own_route.id
        ).id != victim.id
    assert webhook(client, other_headers, status="resolved").status_code == 202
    assert PendingOrchestratedEvent.get_by_id(victim.id).status == "resolved"


@pytest.mark.parametrize("bound", ["group", "team"])
def test_caldav_token_cannot_read_other_member_team(client, db, bound):
    group, other_group = create_group(), create_group()
    user = create_user(group=group)
    own, other = create_team(group), create_team(other_group)
    add_user_to_team(own, user)
    add_user_to_team(other, user)
    headers, _ = personal_token(
        user, **{bound: group if bound == "group" else own},
        scopes=["calendar:read"],
    )
    raw = headers["Authorization"].removeprefix("Bearer ")
    encoded = base64.b64encode(f"{user.username}:{raw}".encode()).decode()
    headers = {"Authorization": f"Basic {encoded}"}
    body = ('<c:calendar-query xmlns:c="urn:ietf:params:xml:ns:caldav" '
            'xmlns:d="DAV:"><d:prop><c:calendar-data/></d:prop></c:calendar-query>')
    denied = client.open(f"/caldav/calendars/teams/{other.id}/", method="REPORT",
                         headers=headers, data=body)
    assert denied.status_code == 404
    allowed = client.open(f"/caldav/calendars/teams/{own.id}/", method="REPORT",
                          headers=headers, data=body)
    assert allowed.status_code == 207


def test_team_token_filters_collections_and_service_writes(client, admin_user, db):
    group = create_group()
    own, other = create_team(group), create_team(group)
    own_service, other_service = create_service(own), create_service(other)
    headers, _ = personal_token(admin_user, team=own)
    for endpoint, expected in (("teams", own.id), ("services", own_service.id)):
        response = client.get(f"/api/{endpoint}", headers=headers)
        assert response.status_code == 200
        assert {item["id"] for item in response.get_json()} == {expected}
    for service, destination in ((other_service, own), (own_service, other)):
        response = client.put(f"/api/services/{service.id}", headers=headers, json={
            "team_id": destination.id, "slug": service.slug, "name": "Unauthorized",
        })
        assert response.status_code == 403
        assert Service.get_by_id(service.id).team_id == service.team_id
    response = client.put(f"/api/services/{own_service.id}", headers=headers,
                          json={"name": "Authorized", "slug": own_service.slug,
                                "team_id": own.id})
    assert response.status_code == 200


def test_bounded_admin_can_grant_roles_only_in_own_group(client, admin_user, db):
    own, other = create_group(), create_group()
    member = create_user()
    headers, _ = personal_token(admin_user, group=own, scopes=["groups:write"])
    payload = {"user_id": member.id, "role": "user_admin", "active": True}
    assert client.post(f"/api/groups/{other.id}/users", headers=headers,
                       json=payload).status_code == 403
    assert client.post(f"/api/groups/{own.id}/users", headers=headers,
                       json=payload).status_code == 201


def test_child_token_inherits_team_and_cannot_widen_scopes(client, admin_user, db):
    team = create_team(create_group())
    headers, _ = personal_token(
        admin_user, team=team, scopes=["profile:write", "teams:read"],
    )
    response = client.post("/api/profile/tokens", headers=headers, json={
        "name": "child", "scopes": ["teams:read"],
    })
    assert response.status_code == 201
    child = ApiToken.get_by_id(response.get_json()["id"])
    assert (child.group_id, child.team_id) == (team.group_id, team.id)
    response = client.post("/api/profile/tokens", headers=headers, json={
        "name": "escape", "scopes": ["teams:write"],
    })
    assert response.status_code == 403


def test_unbounded_token_still_requires_owner_membership(client, db):
    own, other = create_team(create_group()), create_team(create_group())
    user = create_user(group=own.group)
    add_user_to_team(own, user, role="responder")
    create_route(own, source="webhook")
    create_route(other, source="webhook")
    headers, _ = personal_token(user, scopes=["alerts:write"])
    assert webhook(client, headers, team=other).status_code == 403
    assert webhook(client, headers, team=own).status_code == 200


@pytest.mark.parametrize("owner_state", ["inactive", "deleted"])
def test_disabled_owner_cannot_use_existing_token(client, db, owner_state):
    group = create_group()
    user = create_user(group=group)
    team = create_team(group)
    create_route(team, source="webhook")
    headers, _ = personal_token(user, group=group)
    values = {"active": False} if owner_state == "inactive" else {"deleted": True}
    User.update(**values).where(User.id == user.id).execute()
    assert webhook(client, headers, team=team).status_code == 401
    assert client.get("/api/teams", headers=headers).status_code == 401
    assert Alert.select().count() == 0


def test_ownerless_legacy_intake_requires_explicit_bounds(client, db):
    own, other = create_team(create_group()), create_team(create_group())
    create_route(own, source="webhook")
    create_route(other, source="webhook")
    headers, _ = personal_token(None, team=own, scopes=["alerts:write"])
    assert webhook(client, headers, team=other).status_code == 403
    assert webhook(client, headers, team=own).status_code == 200
    unbounded, _ = personal_token(None, scopes=["alerts:write"])
    assert webhook(client, unbounded, team=own).status_code == 401


def test_nagios_personal_ack_is_scoped_to_selected_route(client, admin_user, db):
    from tests.integrations.test_nagios_integration import service_payload

    own, other = create_team(create_group()), create_team(create_group())
    own_route_headers, own_route = route_token(own, source="nagios")
    other_headers, other_route = route_token(other, source="nagios")
    for headers in (other_headers, own_route_headers):
        assert client.post("/api/integrations/nagios", headers=headers,
                           json=service_payload()).status_code == 200
    personal, _ = personal_token(admin_user, team=own, scopes=["alerts:write"])
    denied = client.post("/api/integrations/nagios", headers=personal, json=service_payload(
        notification_type="ACKNOWLEDGEMENT", team=other.slug,
    ))
    assert denied.status_code == 403
    allowed = client.post("/api/integrations/nagios", headers=personal, json=service_payload(
        notification_type="ACKNOWLEDGEMENT", team=own.slug,
    ))
    assert allowed.status_code == 200
    assert Alert.get(Alert.route == other_route.id).group.status == "firing"
    assert Alert.get(Alert.route == own_route.id).group.status == "acknowledged"


def test_orchestration_cannot_redirect_route_credential(client, db):
    group = create_group()
    user = create_user(group=group)
    headers, _ = route_token(create_team(group))
    _, foreign_route = route_token(create_team(group))
    orchestration = create_orchestration(
        group_id=group.id, name=unique("reroute"), scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(draft.id, [{
        "name": "Route elsewhere", "condition_tree": {},
        "actions": [{"type": "set_route", "route_id": foreign_route.id}],
        "processing_mode": "continue",
    }])
    publish_draft(orchestration.id, actor_id=user.id)
    set_runtime_state(orchestration.id, enabled=True, mode="active",
                      compatibility_mode="hybrid")
    assert webhook(client, headers).status_code == 403
    assert Alert.select().count() == 0
    assert PendingOrchestratedEvent.select().count() == 0


def test_legacy_pending_claim_survives_retrigger_and_foreign_resolve(client, db):
    import hashlib

    group = create_group()
    publish_pause(group, create_user(group=group))
    headers, route = route_token(create_team(group))
    other_headers, _ = route_token(create_team(group))
    assert webhook(client, headers).status_code == 202
    pending = PendingOrchestratedEvent.get()
    legacy_key = hashlib.sha256(
        f"{group.id}\x1f{pending.source}\x1f{pending.dedup_key}".encode(),
    ).hexdigest()
    PendingOrchestratedEvent.update(
        active_key=legacy_key, status="activating", claim_token="live-worker",
        claimed_at=utc_now(),
    ).where(PendingOrchestratedEvent.id == pending.id).execute()
    assert webhook(client, other_headers, status="resolved").status_code == 202
    assert webhook(client, headers).status_code == 202
    current = PendingOrchestratedEvent.get_by_id(pending.id)
    assert PendingOrchestratedEvent.select().where(
        PendingOrchestratedEvent.route == route.id,
    ).count() == 1
    assert current.route_id == route.id
    assert current.active_key == legacy_key
    assert current.claim_token == "live-worker"
    assert current.status == "activating"
    assert webhook(client, headers, status="resolved").status_code == 202
    assert PendingOrchestratedEvent.get_by_id(pending.id).status == "resolved"


@pytest.mark.parametrize("change", ["revoke", "scopes", "move"])
def test_team_write_rechecks_authority_at_mutation(client, admin_user, db,
                                                 monkeypatch, change):

    group, other_group = create_group(), create_group()
    team = create_team(group)
    headers, token = personal_token(admin_user, group=group, scopes=["teams:write"])
    original = team_management.update_team

    def change_then_update(team_id, data):
        if change == "revoke":
            ApiToken.update(active=False).where(ApiToken.id == token.id).execute()
        elif change == "scopes":
            ApiToken.update(scopes=["teams:read"]).where(ApiToken.id == token.id).execute()
        else:
            Team.update(group=other_group.id).where(Team.id == team.id).execute()
        return original(team_id, data)

    monkeypatch.setattr(team_management, "update_team", change_then_update)
    response = client.put(f"/api/teams/{team.id}", headers=headers, json={
        "name": "Unauthorized", "slug": team.slug, "group_id": group.id,
    })
    assert response.status_code == 403
    assert Team.get_by_id(team.id).name == team.name


def test_route_rotation_during_intake_stops_write(client, db, monkeypatch):
    from app.services.alerts import lifecycle

    headers, route = route_token(create_team(create_group()))
    original = lifecycle.refresh_authority

    def rotate_then_refresh(**kwargs):
        AlertRoute.update(intake_token_hash=hash_token("replacement")).where(
            AlertRoute.id == route.id,
        ).execute()
        return original(**kwargs)

    monkeypatch.setattr(lifecycle, "refresh_authority", rotate_then_refresh)
    assert webhook(client, headers).status_code == 403
    assert Alert.select().count() == 0


def test_revoked_parent_cannot_issue_token(client, admin_user, db, monkeypatch):
    from contextlib import contextmanager
    from app.modules.db import incident_core_repo

    headers, parent = personal_token(admin_user, scopes=["profile:write"])
    original = incident_core_repo.write_transaction

    @contextmanager
    def revoke_then_begin():
        ApiToken.update(active=False).where(ApiToken.id == parent.id).execute()
        with original():
            yield

    monkeypatch.setattr(incident_core_repo, "write_transaction", revoke_then_begin)
    response = client.post("/api/profile/tokens", headers=headers, json={
        "name": "child", "scopes": ["profile:write"],
    })
    assert response.status_code == 403
    assert ApiToken.select().count() == 1


def test_caldav_discovery_and_event_download_respect_token_bounds(client, db):
    from app.services.caldav.ics import event_href
    from tests.calendar.test_caldav_api import (
        create_team_with_rotation, first_team_event, hrefs_from_response,
    )

    group, own, user = create_team_with_rotation()
    _, other, _ = create_team_with_rotation()
    add_user_to_team(other, user)
    headers, _ = personal_token(user, group=group, scopes=["calendar:read"])
    raw = headers["Authorization"].removeprefix("Bearer ")
    encoded = base64.b64encode(f"{user.username}:{raw}".encode()).decode()
    headers = {"Authorization": f"Basic {encoded}", "Depth": "1"}
    response = client.open("/caldav/calendars/", method="PROPFIND", headers=headers)
    assert response.status_code == 207
    hrefs = hrefs_from_response(response)
    assert f"/caldav/calendars/teams/{own.id}/" in hrefs
    assert f"/caldav/calendars/teams/{other.id}/" not in hrefs
    for method in ("GET", "HEAD"):
        allowed = client.open(event_href(own.id, first_team_event(own)),
                              method=method, headers=headers)
        denied = client.open(event_href(other.id, first_team_event(other)),
                             method=method, headers=headers)
        assert allowed.status_code == 200
        assert denied.status_code == 404


@pytest.mark.parametrize("bound", ["group", "team"])
def test_orchestration_control_plane_respects_token_bounds(client, admin_user, db, bound):
    group, other_group = create_group(), create_group()
    team = create_team(group)
    headers, _ = personal_token(
        admin_user, **{bound: group if bound == "group" else team},
        scopes=["orchestrations:read", "orchestrations:write"],
    )
    own = create_orchestration(group_id=group.id, name=unique("own"), scope="global",
                               created_by_id=admin_user.id)
    other = create_orchestration(group_id=other_group.id, name=unique("other"),
                                 scope="global", created_by_id=admin_user.id)
    for method in ("GET", "DELETE"):
        response = client.open(f"/api/event-orchestrations/{other.id}",
                               method=method, headers=headers)
        assert response.status_code == 403
    own_response = client.delete(f"/api/event-orchestrations/{own.id}", headers=headers)
    assert own_response.status_code == (200 if bound == "group" else 403)


@pytest.mark.parametrize("credential", ["personal", "route"])
def test_intake_rejects_service_moved_out_of_route_team(client, admin_user, db, credential):

    own, other = create_team(create_group()), create_team(create_group())
    headers, route = route_token(own)
    service = create_service(own)
    AlertRoute.update(service=service.id).where(AlertRoute.id == route.id).execute()
    if credential == "personal":
        headers, _ = personal_token(admin_user, team=own, scopes=["alerts:write"])
    assert webhook(client, headers, team=own, fingerprint="before-move").status_code == 200
    service_mutations.update_service(service.id, {"team": other.id})
    response = webhook(client, headers, team=own, fingerprint="after-move")
    assert response.status_code == 403
    assert Alert.select().count() == 1


def test_intake_rechecks_route_ownership_before_write(client, admin_user, db, monkeypatch):
    from app.services.alerts import lifecycle

    own, other = create_team(create_group()), create_team(create_group())
    _, route = route_token(own)
    headers, _ = personal_token(admin_user, team=own, scopes=["alerts:write"])
    original = lifecycle.refresh_authority

    def move_then_refresh(**kwargs):
        AlertRoute.update(team=other.id).where(AlertRoute.id == route.id).execute()
        return original(**kwargs)

    monkeypatch.setattr(lifecycle, "refresh_authority", move_then_refresh)
    assert webhook(client, headers, team=own).status_code == 403
    assert Alert.select().count() == 0


def test_intake_uses_live_parent_group_after_team_move(client, admin_user, db):

    old_group, new_group = create_group(), create_group()
    team = create_team(old_group)
    _, route = route_token(team)
    service = create_service(team)
    AlertRoute.update(service=service.id).where(AlertRoute.id == route.id).execute()
    team_management.update_team(team.id, {"group": new_group.id})
    headers, _ = personal_token(admin_user, group=new_group, scopes=["alerts:write"])
    assert webhook(client, headers, team=team).status_code == 200
    assert Alert.get().service_id == service.id


def wait_for_database_lock(db, backend_pid):
    """Wait for an actual conflicting row lock, not an assumed thread delay."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        row = db.execute_sql(
            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
            (backend_pid,),
        ).fetchone()
        if row and row[0] == "Lock":
            return
        time.sleep(0.02)
    pytest.fail("Concurrent request did not reach the expected database lock")


@pytest.mark.postgresql
def test_ack_and_intake_use_consistent_row_lock_order(app, client, admin_user, db, monkeypatch):
    from app.services.alerts import actions, lifecycle
    from tests.integrations.test_nagios_integration import service_payload

    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires concurrent PostgreSQL row locks")
    team = create_team(create_group())
    route_headers, _ = route_token(team, source="nagios")
    assert client.post("/api/integrations/nagios", headers=route_headers,
                       json=service_payload()).status_code == 200
    ack_headers, _ = personal_token(admin_user, team=team, scopes=["alerts:write"])
    intake_headers, _ = personal_token(admin_user, team=team, scopes=["alerts:write"])
    locked, started, release = Event(), Event(), Event()
    backend = []
    original_lock = actions._lock_group_for_lifecycle
    original_refresh = lifecycle.refresh_authority

    def hold_group(group_id):
        group = original_lock(group_id)
        locked.set()
        assert release.wait(timeout=15)
        return group

    def record_backend(**kwargs):
        backend.append(db.execute_sql("SELECT pg_backend_pid()").fetchone()[0])
        started.set()
        return original_refresh(**kwargs)

    def send(headers, notification_type):
        with app.test_client() as worker:
            return worker.post("/api/integrations/nagios", headers=headers,
                               json=service_payload(notification_type=notification_type,
                                                    team=team.slug)).status_code

    monkeypatch.setattr(actions, "_lock_group_for_lifecycle", hold_group)
    monkeypatch.setattr(lifecycle, "refresh_authority", record_backend)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(send, ack_headers, "ACKNOWLEDGEMENT")
        try:
            assert locked.wait(timeout=10)
            second = executor.submit(send, intake_headers, "PROBLEM")
            assert started.wait(timeout=10)
            wait_for_database_lock(db, backend[0])
        finally:
            release.set()
        assert first.result(timeout=15) == 200
        assert second.result(timeout=15) == 200
    assert Alert.select().count() == 1


@pytest.mark.postgresql
def test_pending_activation_and_resolve_use_consistent_row_lock_order(app, client, db,
                                                                    monkeypatch):
    from app.services.orchestration import pending as pending_service

    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires concurrent PostgreSQL row locks")
    group = create_group()
    publish_pause(group, create_user(group=group))
    headers, _ = route_token(create_team(group))
    assert webhook(client, headers).status_code == 202
    locked, started, release = Event(), Event(), Event()
    backend = []
    original_runtime = pending_service._activation_runtime
    original_refresh = pending_service.refresh_authority

    def hold_pending(row):
        locked.set()
        assert release.wait(timeout=15)
        return original_runtime(row)

    def record_backend(**kwargs):
        backend.append(db.execute_sql("SELECT pg_backend_pid()").fetchone()[0])
        started.set()
        return original_refresh(**kwargs)

    def activate():
        with app.app_context(), db.connection_context():
            return pending_service.process_due_pending_events(now=utc_now() + timedelta(minutes=3))

    def resolve():
        with app.test_client() as worker:
            return webhook(worker, headers, status="resolved").status_code

    monkeypatch.setattr(pending_service, "_activation_runtime", hold_pending)
    monkeypatch.setattr(pending_service, "refresh_authority", record_backend)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(activate)
        try:
            assert locked.wait(timeout=10)
            second = executor.submit(resolve)
            assert started.wait(timeout=10)
            wait_for_database_lock(db, backend[0])
        finally:
            release.set()
        result = first.result(timeout=15)
        assert result["activated"] == 1
        assert result["failed"] == 0
        assert second.result(timeout=15) == 202
    assert Alert.select().count() == 1
