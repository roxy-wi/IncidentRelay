"""Reconnect archived imports without replacing local resource identities."""

from app.modules.db.models import (
    DirectorySyncBinding as Binding, DirectorySyncCurrent as Current,
    DirectorySyncShift as Shift, DirectorySyncSource as Source,
    Rotation, Team, TeamUser, User, UserGroup,
)
from app.services.sync.directory.config import SyncError


def retained_sources(group_ids):
    """List archived sources that still hold unclaimed team or schedule bindings."""
    candidates = Binding.select(Binding.source).where(
        Binding.present == True, Binding.kind == "team",
    )
    for source in Source.select().where(
        Source.deleted == True, Source.group.in_(group_ids), Source.id.in_(candidates),
    ).order_by(Source.id):
        bindings = list(Binding.select().where(Binding.source == source.id))
        ids = managed_team_ids(source, bindings)
        if any(row.kind == "team" and row.present and row.local_id in ids for row in bindings):
            yield source


def managed_team_ids(parent, bindings):
    """Read saved ownership, with a fallback for sources archived before this feature."""
    rotation_team_ids = {
        row.team_id for row in Rotation.select().where(Rotation.id.in_(
            [item.local_id for item in bindings if item.kind == "rotation"],
        ))
    }
    if "retained_team_ids" in (parent.last_result or {}):
        # Disabling management of a matched team releases its team binding but
        # retains imported schedules. Their parent team is needed to reconnect.
        return set(parent.last_result["retained_team_ids"]) | rotation_team_ids
    return {
        item.local_id for item in bindings if item.kind == "team"
        and (item.created or parent.config.get("overwrite_existing") or item.local_id in rotation_team_ids)
    }


def archived_source(source_id, group_id):
    """Require an archived source in the destination group, without leaking details."""
    parent = Source.get_or_none(
        Source.id == source_id, Source.group == group_id, Source.deleted == True,
    )
    if parent is None:
        raise SyncError("Choose a deleted source with retained data in the destination group")
    return parent


def reconnect(source, config):
    """Transfer ownership inside the globally serialized preview/apply transaction.

    Archived bindings remain as inactive provenance. Their external identities
    also identify explicitly reconnected teams on subsequent full imports.
    """
    if config.retained_source_id is None:
        return [], set()
    if not source.last_success_at:
        from app.services.change_intelligence.administration import lock_catalog

        # Team moves/deletions use this lock too; validate the destination after
        # taking it so a concurrent catalog edit cannot change the boundary.
        lock_catalog()
    parent = archived_source(config.retained_source_id, source.group_id)
    original = list(Binding.select().where(Binding.source == parent.id).order_by(Binding.id))
    team_ids = managed_team_ids(parent, original)
    if source.last_success_at:
        return [], team_ids
    if Binding.select().where(Binding.source == source.id).exists() or Shift.select().where(
        Shift.source == source.id,
    ).exists():
        raise SyncError("Retained data can only be connected before the first successful import")

    teams = {row.id: row for row in Team.select().where(Team.id.in_(team_ids), Team.deleted == False)}
    if any(row.group_id != source.group_id for row in teams.values()):
        raise SyncError("A retained team moved outside the destination group; resolve its ownership first")
    available = [item for item in original if item.present]
    teams = {item.local_id: teams[item.local_id] for item in available
             if item.kind == "team" and item.local_id in teams}
    if not teams:
        raise SyncError("Retained data is no longer available; it may already be connected to another source")
    rotations = {row.id: row for row in Rotation.select().where(
        Rotation.id.in_([item.local_id for item in available if item.kind == "rotation" and item.owned]),
        Rotation.deleted == False,
    )}
    if any(row.team_id not in teams for row in rotations.values()):
        raise SyncError("A retained schedule moved to another team; resolve its ownership first")
    for kind, ids in (("team", teams), ("rotation", rotations)):
        if Binding.select().where(
            Binding.kind == kind, Binding.local_id.in_(list(ids)),
            Binding.source.not_in([parent.id, source.id]), Binding.owned == True, Binding.present == True,
        ).exists():
            raise SyncError("Retained resources are managed by another synchronization source")

    changes = []
    models = {"user": User, "group_member": UserGroup, "team_member": TeamUser}
    for item in original:
        owned = item.created
        if item.kind == "team":
            local = teams.get(item.local_id)
            owned = True
        elif item.kind == "rotation":
            local = rotations.get(item.local_id)
            owned = True
        else:
            model = models.get(item.kind)
            local = model.get_or_none(model.id == item.local_id) if model else None
            if item.kind == "group_member" and local and local.group_id != source.group_id:
                raise SyncError("A retained membership moved outside the destination group")
            if item.kind == "team_member" and local and local.team_id not in teams:
                continue
        if local is None or (not item.present and item.kind != "user"):
            continue
        Binding.create(source=source, kind=item.kind, external_id=item.external_id,
                       local_id=item.local_id, owned=owned, created=item.created, present=item.present)
        if item.kind in {"team", "rotation"}:
            changes.append({"kind": item.kind, "external_id": item.external_id, "label": local.name,
                            "action": "reconnect", "fields": {"local_id": local.id, "source_id": parent.id}})

    # Move complete history, including local edits and intervals outside this
    # preview's fetch window. Normal reconciliation reviews any upstream updates.
    for shift in Shift.select().where(Shift.source == parent.id, Shift.rotation.in_(list(rotations))).order_by(Shift.id):
        changes.append({"kind": "shift", "external_id": shift.external_id, "label": shift.title or shift.external_id,
                        "action": "reconnect", "fields": {"local_id": shift.id, "source_id": parent.id}})
    Shift.update(source=source.id).where(Shift.source == parent.id, Shift.rotation.in_(list(rotations))).execute()
    Current.delete().where(Current.rotation.in_(list(rotations))).execute()
    Binding.update(owned=False, present=False).where(Binding.source == parent.id).execute()
    return changes, set(teams)
