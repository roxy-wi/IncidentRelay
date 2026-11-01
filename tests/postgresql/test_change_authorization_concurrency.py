"""Permission mutations and admitted writes use real independent DB connections."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from app.api.schemas.change_integrations import (
    GrantUpdate,
    MachineTokenCreate,
    SourceUpdate,
)
from app.modules.db import services_repo
from app.modules.db.models import (
    ApiToken,
    Change,
    ChangeGrant,
    ChangeIntegration,
    ChangeSource,
)
from app.services.change_intelligence import administration as admin
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    authorize_reference,
    authorized_source,
)
from tests.integrations.test_change_integrations import (
    credential,
    grant,
    revision,
    setup_identity,
)
from tests.integrations.test_change_integration_groups import owned_identity
from tests.integrations.test_change_integration_editing import add_change

__all__ = ["setup_identity", "owned_identity"]  # Shared pytest fixtures.

pytestmark = pytest.mark.postgresql


@pytest.fixture(autouse=True)
def postgres_only(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")


def test_concurrent_grant_edits_reject_stale_revision(db, setup_identity):
    integration, source, _, actor = setup_identity
    permission = grant(setup_identity)
    version = revision(integration)
    barrier = Barrier(2)

    def edit():
        with db.connection_context():
            barrier.wait(timeout=10)
            try:
                admin.update_grant(
                    integration.id,
                    source.id,
                    permission.id,
                    GrantUpdate(expected_revision=version, active=False),
                    actor_id=actor.id,
                )
            except admin.ChangeConflict:
                return "conflict"
            return "updated"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(edit) for _ in range(2)]
        assert sorted(future.result(timeout=15) for future in futures) == [
            "conflict",
            "updated",
        ]
    assert revision(integration) == version + 1
    assert not ChangeGrant.get_by_id(permission.id).active


def test_concurrent_rotation_issues_only_one_replacement(db, setup_identity):
    integration, _, _, actor = setup_identity
    old, _ = credential(setup_identity)
    version = revision(integration)
    barrier = Barrier(2)

    def rotate():
        with db.connection_context():
            barrier.wait(timeout=10)
            try:
                admin.issue_token(
                    integration.id,
                    MachineTokenCreate(expected_revision=version, name="new"),
                    actor_id=actor.id,
                    rotate_token_id=old.id,
                )
            except admin.ChangeConflict:
                return "conflict"
            return "rotated"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(rotate) for _ in range(2)]
        assert sorted(future.result(timeout=15) for future in futures) == [
            "conflict",
            "rotated",
        ]
    assert ApiToken.select().count() == 2
    assert ApiToken.select().where(ApiToken.active == True).count() == 1
    assert revision(integration) == version


def test_check_waiting_for_grant_revocation_rechecks_current_authority(
    db, setup_identity
):
    integration, source, service, actor = setup_identity
    permission = grant(setup_identity)
    locked = Event()
    release = Event()
    started = Event()

    def revoke():
        with (
            db.connection_context(),
            admin.admin_transaction(integration.id, revision(integration)),
        ):
            ChangeGrant.update(active=False).where(
                ChangeGrant.id == permission.id
            ).execute()
            locked.set()
            assert release.wait(timeout=10)
            current = ChangeIntegration.get_by_id(integration.id)
            admin.advance_revision(current)

    def authorize():
        with db.connection_context():
            started.set()
            with pytest.raises(ChangeAccessDenied):
                with authorized_source(
                    integration.id, source.owner_team_id, source.source
                ) as (current, _):
                    authorize_reference(
                        current,
                        "changed",
                        team_id=service.team_id,
                        service_id=service.id,
                    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        revoking = pool.submit(revoke)
        assert locked.wait(timeout=10)
        checking = pool.submit(authorize)
        try:
            assert started.wait(timeout=10)
        finally:
            release.set()
        revoking.result(timeout=15)
        checking.result(timeout=15)


def test_catalog_edit_waits_for_admitted_transaction(db, setup_identity):
    integration, source, service, _ = setup_identity
    grant(setup_identity)
    admitted = Event()
    release = Event()
    editing = Event()
    version = revision(integration)

    def admitted_write():
        with (
            db.connection_context(),
            authorized_source(integration.id, source.owner_team_id, source.source) as (
                current,
                seen,
            ),
        ):
            assert seen == version
            assert (
                authorize_reference(
                    current, "changed", team_id=service.team_id, service_id=service.id
                ).id
                == service.id
            )
            admitted.set()
            assert release.wait(timeout=10)
            assert revision(integration) == version

    def disable():
        with db.connection_context():
            editing.set()
            services_repo.update_service(service.id, {"enabled": False})

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(admitted_write)
        assert admitted.wait(timeout=10)
        editor = pool.submit(disable)
        try:
            assert editing.wait(timeout=10)
        finally:
            release.set()
        writer.result(timeout=15)
        editor.result(timeout=15)
    assert revision(integration) > version
    with pytest.raises(ChangeAccessDenied):
        with authorized_source(integration.id, source.owner_team_id, source.source) as (
            current,
            _,
        ):
            authorize_reference(
                current, "changed", team_id=service.team_id, service_id=service.id
            )


def test_token_issue_waiting_for_role_revocation_rechecks_membership(
    db, owned_identity
):
    """A stale HTTP principal cannot issue a token after membership revocation."""
    from app.modules.db.models import UserGroup

    integration, _, _, manager = owned_identity
    revoked = Event()
    release = Event()
    issuing = Event()
    version = revision(integration)

    def revoke_role():
        with db.connection_context(), db.atomic():
            UserGroup.update(role="viewer").where(
                UserGroup.user == manager.id
            ).execute()
            revoked.set()
            assert release.wait(timeout=10)

    def issue():
        with db.connection_context():
            issuing.set()
            with pytest.raises(ChangeIntegration.DoesNotExist):
                admin.issue_token(
                    integration.id,
                    MachineTokenCreate(expected_revision=version, name="Denied"),
                    actor_id=manager.id,
                )

    with ThreadPoolExecutor(max_workers=2) as pool:
        revoking = pool.submit(revoke_role)
        assert revoked.wait(timeout=10)
        writer = pool.submit(issue)
        try:
            assert issuing.wait(timeout=10)
        finally:
            release.set()
        revoking.result(timeout=15)
        writer.result(timeout=15)
    assert not ApiToken.select().exists()


def test_group_disable_serializes_with_empty_integration_token_issue(
    db, owned_identity
):
    """Owner Group changes invalidate even identities that have no sources yet."""
    from app.modules.db import groups_repo

    _, _, service, manager = owned_identity
    integration = admin.create_integration(
        "Empty", owner_group_id=service.group_id, actor_id=manager.id
    )
    disabled = Event()
    release = Event()
    issuing = Event()

    def disable_group():
        with db.connection_context(), db.atomic():
            groups_repo.update_group(service.group_id, {"active": False})
            disabled.set()
            assert release.wait(timeout=10)

    def issue():
        with db.connection_context():
            issuing.set()
            with pytest.raises(ChangeIntegration.DoesNotExist):
                admin.issue_token(
                    integration.id,
                    MachineTokenCreate(expected_revision=1, name="Denied"),
                    actor_id=manager.id,
                )

    with ThreadPoolExecutor(max_workers=2) as pool:
        disabling = pool.submit(disable_group)
        assert disabled.wait(timeout=10)
        writer = pool.submit(issue)
        try:
            assert issuing.wait(timeout=10)
        finally:
            release.set()
        disabling.result(timeout=15)
        writer.result(timeout=15)
    assert not ApiToken.select().exists()


def test_first_change_committing_before_rename_locks_source_identity(
    db, setup_identity
):
    integration, source, _, actor = setup_identity
    admitted, release, editing = Event(), Event(), Event()
    version = revision(integration)

    def ingest():
        with (
            db.connection_context(),
            authorized_source(integration.id, source.owner_team_id, source.source),
        ):
            add_change(integration, source)
            admitted.set()
            assert release.wait(timeout=10)

    def rename():
        with db.connection_context():
            editing.set()
            with pytest.raises(admin.ChangeConflict, match="already has Changes"):
                admin.update_source(
                    integration.id,
                    source.id,
                    SourceUpdate(expected_revision=version, source="renamed"),
                    actor_id=actor.id,
                )

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(ingest)
        assert admitted.wait(timeout=10)
        editor = pool.submit(rename)
        try:
            assert editing.wait(timeout=10)
        finally:
            release.set()
        writer.result(timeout=15)
        editor.result(timeout=15)
    assert Change.select().count() == 1
    assert ChangeSource.get_by_id(source.id).source == source.source


def test_rename_committing_before_intake_rejects_old_namespace(db, setup_identity):
    integration, source, _, actor = setup_identity
    edited, release, admitting = Event(), Event(), Event()
    version = revision(integration)

    def rename():
        with db.connection_context(), admin.admin_transaction(integration.id, version):
            admin.update_source(
                integration.id,
                source.id,
                SourceUpdate(expected_revision=version, source="renamed"),
                actor_id=actor.id,
            )
            edited.set()
            assert release.wait(timeout=10)

    def ingest():
        with db.connection_context():
            admitting.set()
            with pytest.raises(ChangeAccessDenied):
                with authorized_source(
                    integration.id, source.owner_team_id, source.source
                ):
                    add_change(integration, source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        editor = pool.submit(rename)
        assert edited.wait(timeout=10)
        writer = pool.submit(ingest)
        try:
            assert admitting.wait(timeout=10)
        finally:
            release.set()
        editor.result(timeout=15)
        writer.result(timeout=15)
    assert not Change.select().exists()
    assert ChangeSource.get_by_id(source.id).source == "renamed"


def test_concurrent_default_source_creation_keeps_unique_names(db, setup_identity):
    _, _, service, actor = setup_identity
    barrier = Barrier(2)

    def create():
        with db.connection_context():
            barrier.wait(timeout=10)
            integration = admin.create_integration(
                "Same release", actor_id=actor.id, owner_team_id=service.team_id
            )
            return ChangeSource.get(ChangeSource.integration == integration.id).source

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        names = [future.result(timeout=15) for future in futures]
    assert len(set(names)) == 2


def test_concurrent_permission_retargets_reject_stale_edit(db, setup_identity):
    from tests.factories import create_service

    integration, source, service, actor = setup_identity
    permission = grant(setup_identity, service=service.id)
    targets = [create_service(service.team).id, create_service(service.team).id]
    version = revision(integration)
    barrier = Barrier(2)

    def edit(target):
        with db.connection_context():
            barrier.wait(timeout=10)
            try:
                admin.update_grant(
                    integration.id,
                    source.id,
                    permission.id,
                    GrantUpdate(expected_revision=version, target_service_id=target),
                    actor_id=actor.id,
                )
            except admin.ChangeConflict:
                return "conflict"
            return "updated"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(edit, target) for target in targets]
        assert sorted(future.result(timeout=15) for future in futures) == [
            "conflict",
            "updated",
        ]
    assert ChangeGrant.select().count() == 1
    assert ChangeGrant.get_by_id(permission.id).target_service_id in targets
