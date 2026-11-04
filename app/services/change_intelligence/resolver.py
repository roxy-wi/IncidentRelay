"""Bounded reference reconciliation with current authority and pinned identities."""

from datetime import timedelta

from peewee import fn

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import (
    Change,
    ChangeGraphState,
    ChangeGrant,
    ChangeIntegration,
    ChangeService,
    ChangeServiceReference,
    ChangeSource,
    Group,
    Service,
    Team,
)
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    active_integration_group,
    authorize_reference,
    lock_row,
    scoped_team,
)
from app.services.change_intelligence.references import mapping_summary
from app.settings import Config

ENGINE_VERSION = "references-v1"
BLOCKED_STATES = {"denied", "invalid", "expired"}


class StaleChangeInputs(RuntimeError):
    """The snapshot must be discarded and recalculated under current inputs."""


def _usable_namespace(team_id):
    return (
        Team.select()
        .join(Group)
        .where(
            Team.id == team_id,
            Team.active == True,
            Team.deleted == False,
            Group.active == True,
            Group.deleted == False,
        )
        .exists()
    )


def _reference_result(reference, source, integration, stamp):
    """Resolve only a pinned ID/namespace, without consulting the ingest token."""
    now = utc_now()
    expires = reference.expires_at
    if reference.resolved_service_id is None and expires is None:
        expires = reference.created_at + timedelta(
            seconds=Config.CHANGE_PENDING_TTL_SECONDS
        )
    state, service_id, verification, error = (
        "resolved",
        reference.resolved_service_id,
        "rejected",
        None,
    )
    basis = "reference_grant"
    if (
        reference.resolution_status in BLOCKED_STATES
        and reference.last_error_code != "retry_requested"
    ):
        state, error = reference.resolution_status, reference.last_error_code
    elif (
        not integration.active
        or not source.active
        or not active_integration_group(integration)
    ):
        state, error = "denied", "integration_or_source_disabled"
    elif not _usable_namespace(reference.namespace_team_id):
        state, error = "invalid", "namespace_unavailable"
    elif service_id is None and expires is not None and expires <= now:
        state, error = "expired", "pending_ttl_expired"
    else:
        existing = Service.get_or_none(Service.id == service_id) if service_id else None
        if service_id and (
            existing is None
            or existing.team_id != reference.namespace_team_id
            or existing.deleted
            or not existing.enabled
        ):
            state, error = "invalid", "service_unavailable_or_moved"
        else:
            try:
                # Read-only transaction: authorization requires transaction context,
                # while publication later rechecks its revision under locks.
                with db.atomic():
                    scoped_team(integration, source.owner_team_id)
                    service = authorize_reference(
                        source,
                        "changed"
                        if reference.relation_type == "changed"
                        else "reference",
                        team_id=reference.namespace_team_id,
                        service_id=service_id,
                        service_slug=reference.requested_service_slug
                        if service_id is None
                        else None,
                    )
                if service is None:
                    state = "pending_resolution"
                else:
                    service_id = service.id
                    trusted = (
                        reference.relation_type == "changed"
                        or ChangeGrant.select()
                        .where(
                            ChangeGrant.source == source.id,
                            ChangeGrant.active == True,
                            ChangeGrant.target_team == reference.namespace_team_id,
                            ChangeGrant.capability == "reported_affected",
                            ChangeGrant.target_service.is_null(True)
                            | (ChangeGrant.target_service == service_id),
                        )
                        .exists()
                    )
                    verification = "trusted" if trusted else "unverified"
                    basis = (
                        f"{reference.relation_type if trusted else 'reference'}_grant"
                    )
            except ChangeAccessDenied:
                state, error = "denied", "grant_or_owner_unavailable"
    if state == "pending_resolution":
        verification = "unverified"
    evidence = {
        "basis": basis,
        "auth_revision": stamp["auth_revision"],
        "graph_revision": stamp["graph_revision"],
    }
    return {
        "resolution_status": state,
        "resolved_service": service_id,
        "verification_state": verification,
        "verification_evidence": evidence,
        "expires_at": expires,
        "last_error_code": error,
        "resolved_at": reference.resolved_at or (now if state == "resolved" else None),
        "last_attempt_at": now,
        "attempts": reference.attempts + 1,
    }


def compute_reference_batch(claim):
    """Capture revisions before input reads and perform no projection writes."""
    graph_revision = ChangeGraphState.get_by_id(1).revision
    change = Change.get_or_none(Change.id == claim.entity_id)
    if change is None:
        return None
    integration = ChangeIntegration.get_by_id(change.integration_id)
    stamp = {
        "target_revision": change.revision,
        "auth_revision": integration.auth_revision,
        "graph_revision": graph_revision,
    }
    source = ChangeSource.get_by_id(change.source_id)
    cursor = claim.cursor or {}
    if any(cursor.get(key) != value for key, value in stamp.items()):
        cursor = {}
    upper = cursor.get("upper_id")
    if upper is None:
        upper = (
            ChangeServiceReference.select(fn.MAX(ChangeServiceReference.id))
            .where(ChangeServiceReference.change == change.id)
            .scalar()
            or 0
        )
    rows = list(
        ChangeServiceReference.select()
        .where(
            ChangeServiceReference.change == change.id,
            ChangeServiceReference.id > cursor.get("after_id", 0),
            ChangeServiceReference.id <= upper,
        )
        .order_by(ChangeServiceReference.id)
        .limit(Config.CHANGE_WORKER_BATCH_SIZE)
    )
    results = []
    for index, reference in enumerate(rows):
        if index % 10 == 0:
            changes_repo.renew_lease(claim)
        results.append(
            (reference, _reference_result(reference, source, integration, stamp))
        )
    after = rows[-1].id if rows else upper
    return {
        "change": change,
        "stamp": stamp,
        "results": results,
        "upper_id": upper,
        "after_id": after,
        "complete": after >= upper or len(rows) < Config.CHANGE_WORKER_BATCH_SIZE,
    }


def _publish_link(change, service_id, relation, stamp):
    """Merge aliases using only references checked under the current authority."""
    refs = list(
        ChangeServiceReference.select()
        .where(
            ChangeServiceReference.change == change.id,
            ChangeServiceReference.resolved_service == service_id,
            ChangeServiceReference.relation_type == relation,
        )
        .order_by(ChangeServiceReference.id)
    )
    supported = [
        ref
        for ref in refs
        if ref.resolution_status == "resolved"
        and ref.verification_state in {"trusted", "unverified"}
        and all(
            ref.verification_evidence.get(key) == stamp[key]
            for key in ("auth_revision", "graph_revision")
        )
    ]
    verification = "rejected"
    if supported:
        verification = (
            "trusted"
            if any(ref.verification_state == "trusted" for ref in supported)
            else "unverified"
        )
    evidence = {
        "basis": "direct_grants",
        "reference_ids": [ref.id for ref in supported[:20]],
        "auth_revision": stamp["auth_revision"],
        "graph_revision": stamp["graph_revision"],
    }
    link = ChangeService.get_or_none(
        ChangeService.change == change.id,
        ChangeService.service == service_id,
        ChangeService.relation_type == relation,
    )
    values = {
        "verification_state": verification,
        "verification_evidence": evidence,
        "input_stamp": {
            "change_revision": change.revision,
            "auth_revision": stamp["auth_revision"],
            "graph_revision": stamp["graph_revision"],
            "engine_version": ENGINE_VERSION,
        },
        "updated_at": utc_now(),
    }
    if link:
        ChangeService.update(**values).where(ChangeService.id == link.id).execute()
    elif supported:
        service = Service.get_by_id(service_id)
        ChangeService.create(
            change=change.id,
            service=service_id,
            relation_type=relation,
            first_reference=supported[0].id,
            identity_snapshot={
                "team_id": supported[0].namespace_team_id,
                "service_id": service_id,
                "service_slug": service.slug,
            },
            **values,
        )


def publish_reference_batch(claim, plan):
    """Validate inputs and lease through commit; a lost claim rolls back writes."""
    with incident_core_repo.write_transaction():
        if plan is None:
            changes_repo.lock_claim(claim)
            changes_repo.finish_claim(claim, error_class="entity_missing")
            return
        graph = lock_row(ChangeGraphState.select().where(ChangeGraphState.id == 1))
        integration = lock_row(
            ChangeIntegration.select().where(
                ChangeIntegration.id == plan["change"].integration_id
            )
        )
        change = lock_row(Change.select().where(Change.id == claim.entity_id))
        stamp = plan["stamp"]
        if (
            change is None
            or graph.revision != stamp["graph_revision"]
            or integration.auth_revision != stamp["auth_revision"]
            or change.revision != stamp["target_revision"]
        ):
            raise StaleChangeInputs()
        changes_repo.lock_claim(claim)
        touched = set()
        changed = False
        for reference, values in plan["results"]:
            material = any(
                getattr(
                    reference,
                    "resolved_service_id" if name == "resolved_service" else name,
                )
                != value
                for name, value in values.items()
                if name not in {"last_attempt_at", "attempts"}
            )
            if material:
                changed = True
                values["verification_version"] = reference.verification_version + 1
            ChangeServiceReference.update(**values).where(
                ChangeServiceReference.id == reference.id
            ).execute()
            if values["resolved_service"]:
                touched.add((values["resolved_service"], reference.relation_type))
        mapping_status, _ = mapping_summary(change.id)
        if changed or mapping_status != change.mapping_status:
            change.revision += 1
            Change.update(
                revision=change.revision,
                mapping_status=mapping_status,
                updated_at=utc_now(),
            ).where(Change.id == change.id).execute()
        for service_id, relation in sorted(touched):
            _publish_link(change, service_id, relation, stamp)
        stamp = {
            **stamp,
            "target_revision": change.revision,
            "engine_version": ENGINE_VERSION,
        }
        cursor = None
        delay = None
        if not plan["complete"]:
            cursor = {
                **stamp,
                "after_id": plan["after_id"],
                "upper_id": plan["upper_id"],
            }
            delay = 0
        else:
            # Every reference was checked under these inputs across the batches.
            ChangeService.update(
                input_stamp={
                    "change_revision": change.revision,
                    "auth_revision": stamp["auth_revision"],
                    "graph_revision": stamp["graph_revision"],
                    "engine_version": ENGINE_VERSION,
                }
            ).where(ChangeService.change == change.id).execute()
            if (
                ChangeServiceReference.select()
                .where(
                    ChangeServiceReference.change == change.id,
                    ChangeServiceReference.resolution_status == "pending_resolution",
                )
                .exists()
            ):
                delay = Config.CHANGE_PENDING_POLL_SECONDS
        if plan["complete"]:
            from app.services.change_intelligence.correlation import request_after_mapping

            request_after_mapping(change)
        changes_repo.finish_claim(claim, cursor=cursor, delay=delay, stamp=stamp)
