from app.login import create_access_token
from app.modules.db.models import AuditLog
from tests.factories import create_group, create_team, create_user


def _headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _entry(**kwargs):
    defaults = {
        "action": "test.action",
        "object_type": "test_object",
        "object_id": 1,
        "data": {"changed": True},
    }
    defaults.update(kwargs)
    return AuditLog.create(**defaults)


def test_global_admin_can_read_all_audit_entries(client, admin_headers, db):
    first_group = create_group(name="First")
    second_group = create_group(name="Second")
    team = create_team(first_group, name="First team")

    _entry(action="global.change")
    _entry(action="group.change", group=second_group)
    _entry(action="team.change", team=team)

    response = client.get("/api/admin/audit-logs", headers=admin_headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert {item["action"] for item in payload["items"]} == {
        "global.change",
        "group.change",
        "team.change",
    }
    assert payload["permissions"]["is_global_admin"] is True
    assert payload["permissions"]["group_ids"] is None


def test_group_editor_sees_only_direct_and_team_logs_from_editor_groups(client, db):
    editable_group = create_group(name="Editable")
    hidden_group = create_group(name="Hidden")
    editable_team = create_team(editable_group, name="Editable team")
    hidden_team = create_team(hidden_group, name="Hidden team")
    editor = create_user(
        username="audit-editor",
        group=editable_group,
        group_role="editor",
    )

    _entry(action="global.change")
    _entry(action="editable.direct", group=editable_group)
    _entry(action="editable.team", team=editable_team)
    _entry(action="hidden.direct", group=hidden_group)
    _entry(action="hidden.team", team=hidden_team)

    response = client.get(
        "/api/admin/audit-logs",
        headers=_headers(editor),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert {item["action"] for item in payload["items"]} == {
        "editable.direct",
        "editable.team",
    }
    assert payload["permissions"] == {
        "is_global_admin": False,
        "group_ids": [editable_group.id],
    }
    assert payload["items"][0]["group"]["id"] == editable_group.id
    assert {group["id"] for group in payload["filters"]["groups"]} == {
        editable_group.id,
    }


def test_group_editor_cannot_filter_another_group(client, db):
    editable_group = create_group(name="Editable")
    hidden_group = create_group(name="Hidden")
    editor = create_user(
        username="scoped-editor",
        group=editable_group,
        group_role="editor",
    )

    response = client.get(
        f"/api/admin/audit-logs?group_id={hidden_group.id}",
        headers=_headers(editor),
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "audit_log_group_access_denied"


def test_viewer_and_group_user_admin_cannot_read_audit_log(client, db):
    group = create_group(name="Restricted")
    viewer = create_user(
        username="audit-viewer",
        group=group,
        group_role="viewer",
    )
    user_admin = create_user(
        username="audit-user-admin",
        group=group,
        group_role="user_admin",
    )

    for user in (viewer, user_admin):
        response = client.get(
            "/api/admin/audit-logs",
            headers=_headers(user),
        )
        assert response.status_code == 403
        assert response.get_json()["error"] == "audit_log_access_denied"


def test_editor_with_multiple_roles_sees_only_editor_group(client, db):
    editable_group = create_group(name="Editable")
    admin_group = create_group(name="User administration")
    editor = create_user(
        username="mixed-audit-user",
        group=editable_group,
        group_role="editor",
    )
    from app.modules.db.models import UserGroup

    UserGroup.create(
        user=editor,
        group=admin_group,
        role="user_admin",
        active=True,
    )

    _entry(action="editor.visible", group=editable_group)
    _entry(action="user-admin.hidden", group=admin_group)

    response = client.get(
        "/api/admin/audit-logs",
        headers=_headers(editor),
    )

    assert response.status_code == 200
    assert [item["action"] for item in response.get_json()["items"]] == [
        "editor.visible",
    ]


def test_audit_log_supports_filters_and_pagination(client, admin_headers, db):
    group = create_group(name="Payments")
    actor = create_user(username="alice")
    other_actor = create_user(username="bob")

    for index in range(5):
        _entry(
            action="service.update" if index % 2 == 0 else "route.update",
            object_type="service" if index % 2 == 0 else "route",
            object_id=index + 1,
            group=group,
            user=actor if index < 4 else other_actor,
            message=f"Changed item {index + 1}",
        )

    response = client.get(
        "/api/admin/audit-logs"
        f"?group_id={group.id}"
        f"&actor_id={actor.id}"
        "&action=service.update"
        "&object_type=service"
        "&search=Changed"
        "&page=1&page_size=2",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["items"]) == 2
    assert payload["pagination"]["total_items"] == 2
    assert payload["summary"]["total"] == 2
    assert all(item["actor"]["id"] == actor.id for item in payload["items"])
    assert all(item["action"] == "service.update" for item in payload["items"])


def test_audit_log_page_access_matches_api_scope(client, db, admin_headers):
    group = create_group(name="Page access")
    editor = create_user(
        username="page-editor",
        group=group,
        group_role="editor",
    )
    viewer = create_user(
        username="page-viewer",
        group=group,
        group_role="viewer",
    )

    assert client.get("/admin/audit-log", headers=admin_headers).status_code == 200
    assert client.get("/admin/audit-log", headers=_headers(editor)).status_code == 200
    assert client.get("/admin/audit-log", headers=_headers(viewer)).status_code == 403
