from app.modules.db import groups_repo
from app.api.schemas.roles import GROUP_VIEWER_ROLE
from tests.factories import (
    create_group,
    create_user,
    unique
)


def test_add_user_to_group_respects_active_flag(db):
    group = create_group(slug=unique("group"))
    user = create_user(username=unique("user"))

    membership = groups_repo.add_user_to_group(
        user_id=user.id,
        group_id=group.id,
        role=GROUP_VIEWER_ROLE,
        active=False,
    )

    assert membership.active is False

    membership = groups_repo.get_group_membership(membership.id)

    assert membership.active is False


def test_readd_user_to_group_respects_active_flag(db):
    group = create_group(slug=unique("group"))
    user = create_user(username=unique("user"))

    groups_repo.add_user_to_group(
        user_id=user.id,
        group_id=group.id,
        role=GROUP_VIEWER_ROLE,
        active=True,
    )

    membership = groups_repo.add_user_to_group(
        user_id=user.id,
        group_id=group.id,
        role=GROUP_VIEWER_ROLE,
        active=False,
    )

    assert membership.active is False
