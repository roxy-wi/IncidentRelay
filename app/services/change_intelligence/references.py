"""Resolve scoped identities while preserving the first pinned namespace."""

from peewee import fn

from app.modules.common import utc_now
from app.modules.db.models import (
    ChangeGrant,
    ChangeService,
    ChangeServiceReference,
    Service,
    Team,
)
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    authorize_reference,
    scoped_team,
)


class InvalidChangeInput(ValueError):
    """Invalid identity inside a namespace the sender is allowed to inspect."""


def resolve_reference(change, event, source, relation, submitted, auth_revision):
    """Persist one original reference and, when resolved, its canonical link."""
    service_id = submitted.get("service_id")
    slug = submitted.get("service_slug")
    team_id = submitted.get("team_id")
    if submitted.get("team_slug"):
        team = Team.get_or_none(Team.slug == submitted["team_slug"])
        if team is None:
            raise ChangeAccessDenied("Change access denied")
        team_id = team.id
    if service_id is not None and team_id is None:
        existing = ChangeServiceReference.get_or_none(
            ChangeServiceReference.change == change.id,
            ChangeServiceReference.relation_type == relation,
            ChangeServiceReference.normalized_ref_key == f"id:{service_id}",
        )
        service = Service.get_or_none(Service.id == service_id)
        if existing:
            team_id = existing.namespace_team_id
        elif service:
            team_id = service.team_id
        else:
            # No namespace was supplied: a missing ID must not disclose scope.
            raise ChangeAccessDenied("Change access denied")
    team_id = team_id or source.owner_team_id
    scoped_team(source.integration, team_id)
    key = (
        f"id:{service_id}"
        if service_id is not None
        else f"slug:team-id:{team_id}/{slug}"
    )
    reference = ChangeServiceReference.get_or_none(
        ChangeServiceReference.change == change.id,
        ChangeServiceReference.relation_type == relation,
        ChangeServiceReference.normalized_ref_key == key,
    )
    if reference and reference.namespace_team_id != team_id:
        raise ChangeAccessDenied("Change access denied")
    capability = "changed" if relation == "changed" else "reference"
    lookup_id = (
        reference.resolved_service_id
        if reference and reference.resolved_service_id
        else service_id
    )
    try:
        service = authorize_reference(
            source,
            capability,
            team_id=team_id,
            service_id=lookup_id,
            service_slug=slug if lookup_id is None else None,
        )
    except ChangeAccessDenied:
        capabilities = (
            ["changed"]
            if capability == "changed"
            else ["reference", "changed", "reported_affected"]
        )
        can_inspect_team = (
            ChangeGrant.select()
            .where(
                ChangeGrant.source == source.id,
                ChangeGrant.active == True,
                ChangeGrant.target_team == team_id,
                ChangeGrant.target_service.is_null(True),
                ChangeGrant.capability.in_(capabilities),
            )
            .exists()
        )
        if (
            can_inspect_team
            and lookup_id
            and not Service.select()
            .where(
                Service.id == lookup_id,
                Service.team == team_id,
                Service.enabled == True,
                Service.deleted == False,
            )
            .exists()
        ):
            # A foreign ID and an absent ID must look identical inside an
            # explicitly authorized namespace. Never probe global existence.
            raise InvalidChangeInput(
                "Unknown Service ID in the permitted namespace"
            ) from None
        raise
    trusted = relation == "changed"
    if relation == "reported_affected":
        trusted = (
            ChangeGrant.select()
            .where(
                ChangeGrant.source == source.id,
                ChangeGrant.active == True,
                ChangeGrant.target_team == team_id,
                ChangeGrant.capability == "reported_affected",
                (
                    ChangeGrant.target_service.is_null(True)
                    | (ChangeGrant.target_service == (service.id if service else -1))
                ),
            )
            .exists()
        )
    verification = "trusted" if trusted else "unverified"
    evidence = {
        "basis": f"{relation if trusted else 'reference'}_grant",
        "auth_revision": auth_revision,
    }
    if reference is None:
        reference = ChangeServiceReference.create(
            change=change.id,
            first_event=event.id,
            relation_type=relation,
            ref_type="id" if service_id else "slug",
            requested_service_id=service_id,
            requested_service_slug=slug,
            requested_team_id=submitted.get("team_id"),
            requested_team_slug=submitted.get("team_slug"),
            namespace_team=team_id,
            normalized_ref_key=key,
            resolved_service=service.id if service else None,
            resolution_status="resolved" if service else "pending_resolution",
            verification_state=verification,
            verification_evidence=evidence,
            resolved_at=utc_now() if service else None,
        )
    else:
        updates = {
            "verification_state": verification,
            "verification_evidence": evidence,
            "verification_version": reference.verification_version + 1,
        }
        if reference.resolved_service_id is None and service:
            updates.update(
                resolved_service=service.id,
                resolution_status="resolved",
                resolved_at=utc_now(),
            )
        ChangeServiceReference.update(**updates).where(
            ChangeServiceReference.id == reference.id
        ).execute()
    if service:
        # An alias never rebinds an existing canonical relationship. Refresh only
        # direct permission evidence, which is valid under the held auth lock.
        link = ChangeService.get_or_none(
            ChangeService.change == change.id,
            ChangeService.service == service.id,
            ChangeService.relation_type == relation,
        )
        values = {
            "verification_state": verification,
            "verification_evidence": evidence,
            "input_stamp": {
                "change_revision": change.revision,
                "auth_revision": auth_revision,
            },
            "updated_at": utc_now(),
        }
        if link:
            ChangeService.update(**values).where(ChangeService.id == link.id).execute()
        else:
            ChangeService.create(
                change=change.id,
                service=service.id,
                relation_type=relation,
                first_reference=reference.id,
                identity_snapshot={
                    "team_id": team_id,
                    "service_id": service.id,
                    "service_slug": service.slug,
                },
                **values,
            )


def mapping_summary(change_id):
    """Return safe counts and aggregate mapping status, without Service data."""
    counts = dict(
        ChangeServiceReference.select(
            ChangeServiceReference.resolution_status,
            fn.COUNT(ChangeServiceReference.id),
        )
        .where(ChangeServiceReference.change == change_id)
        .group_by(
            ChangeServiceReference.resolution_status,
        )
        .tuples()
    )
    total = sum(counts.values())
    resolved = counts.get("resolved", 0)
    pending = counts.get("pending_resolution", 0)
    if resolved:
        status = "mapped" if resolved == total else "partially_mapped"
    else:
        status = "unmapped" if not total or pending else "mapping_failed"
    return status, {"total": total, "resolved": resolved, "pending": pending}
