"""Group mutations and corresponding audit must commit or roll back together."""

from app.modules.db.models import UserGroup
from app.views import groups_view
from tests.factories import create_group, create_user, unique


def _fail_audit(*args, **kwargs):
    raise RuntimeError("audit persistence failed")


def test_group_update_rolls_back_when_audit_fails(client, db, auth_headers, monkeypatch):
    group = create_group()
    before = (group.name, group.slug, group.description, group.active)
    monkeypatch.setattr(groups_view, "write_audit", _fail_audit)
    response = client.put(
        f"/api/groups/{group.id}", headers=auth_headers,
        json={"name": "Changed group", "slug": unique("group-new"), "active": False},
    )
    assert response.status_code == 500
    group = type(group).get_by_id(group.id)
    assert (group.name, group.slug, group.description, group.active) == before


def test_group_membership_add_rolls_back_when_audit_fails(
    client, db, auth_headers, monkeypatch,
):
    group = create_group()
    user = create_user()
    monkeypatch.setattr(groups_view, "write_audit", _fail_audit)
    response = client.post(
        f"/api/groups/{group.id}/users", headers=auth_headers,
        json={"user_id": user.id, "role": "viewer", "active": True},
    )
    assert response.status_code == 500
    assert not UserGroup.select().where(
        (UserGroup.group == group.id) & (UserGroup.user == user.id)
    ).exists()
