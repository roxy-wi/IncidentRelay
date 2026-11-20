"""Remove source ownership with an explicit choice about imported resources."""

from app.modules.common import utc_now
from app.modules.db import rotations_repo, teams_repo
from app.modules.db.models import (
    DirectorySyncBinding as Binding, DirectorySyncCurrent as Current,
    DirectorySyncShift as Shift, Rotation, Team,
)
from app.modules.db.transactions import lock_row
from app.services.sync.directory.config import SyncError


def remove_source(source, *, delete_imported):
    """Archive a locked idle source within the caller's write transaction."""
    from app.services.sync.cmdb.config import is_cmdb

    if is_cmdb(source.config):
        from app.services.sync.cmdb.reconcile import remove_catalog
        return remove_catalog(source, delete_imported=delete_imported)
    if delete_imported:
        from app.services.change_intelligence.administration import lock_catalog

        # Follow the lock order used by normal team lifecycle changes.
        lock_catalog()
        bindings = Binding.select().where(Binding.source == source.id)
        result = source.last_result or {}
        team_bindings = list(bindings.where(Binding.kind == "team"))
        known_schedules = {row.external_id for row in bindings.where(Binding.kind == "rotation")}
        # Unmanaged matched teams are intentionally skipped during import, so
        # their upstream schedules need not have local rotation bindings.
        missing_schedules = set()
        if all(row.owned for row in team_bindings):
            missing_schedules = set(result.get("schedule_ids", [])) - known_schedules
        if missing_schedules or result.get("teams", 0) > len(team_bindings):
            raise SyncError(
                "Imported resource bindings are missing; cannot identify all teams and rotations to delete. "
                "Nothing was deleted. Delete the old resources explicitly, then remove the source "
                "with the keep-data option."
            )
        owned = Binding.select(Binding.local_id).where(
            Binding.source == source.id, Binding.created == True, Binding.owned == True,
        )
        team_ids = {row.local_id for row in owned.where(Binding.kind == "team")}
        rotation_ids = [row.local_id for row in owned.where(Binding.kind == "rotation").order_by(Binding.local_id)]
        rotations = []
        for key in rotation_ids:
            rotation = lock_row(Rotation.select().where(Rotation.id == key))
            if rotation:
                rotations.append(rotation)
        # A concurrent team move must not invalidate the destination-group check.
        locked_teams = {key: lock_row(Team.select().where(Team.id == key))
                        for key in sorted(team_ids | {rotation.team_id for rotation in rotations})}
        teams = [locked_teams[key] for key in sorted(team_ids) if locked_teams[key]]
        if any(not team or team.group_id != source.group_id for team in locked_teams.values()):
            raise SyncError(
                "Imported resources moved outside the destination group; "
                "keep the data or resolve their ownership first"
            )
        # Use normal deletion so routes, escalation targets and other dependent
        # operational state receive the same cleanup as a manual resource deletion.
        for team in teams:
            if not team.deleted:
                teams_repo.soft_delete_team(team.id)
        for rotation in rotations:
            if not Rotation.get_by_id(rotation.id).deleted:
                rotations_repo.soft_delete_rotation(rotation.id)
        Shift.delete().where(Shift.source == source.id).execute()
        Binding.delete().where(Binding.source == source.id).execute()
    else:
        # Ownership is released below. Keep explicit team provenance for a later
        # reconnection, including matched teams that have no schedules yet.
        source.last_result = {**(source.last_result or {}), "retained_team_ids": [
            row.local_id for row in Binding.select().where(
                Binding.source == source.id, Binding.kind == "team",
                Binding.owned == True, Binding.present == True,
            ).order_by(Binding.local_id)
        ]}
        # Concrete intervals still use their existing editor/calendar. Retain only
        # rotation ownership; people and team memberships become locally managed.
        Binding.update(owned=False).where(Binding.source == source.id, Binding.kind != "rotation").execute()

    Current.delete().where(Current.source == source.id).execute()
    source.config = {**source.config, "editable": True, "membership_authority": "oidc",
                     "operations": {key: value for key, value in source.config.get("operations", {}).items()
                                    if key != "current"}}
    source.deleted = True
    source.deleted_at = utc_now()
    source.enabled = False
    source.revision += 1
    source.approved_revision = None
    source.headers_encrypted = None
    source.preview_encrypted = None
    source.preview_token = None
    source.preview_result = None
    source.preview_until = None
    source.pending_mode = None
    source.pending_preview_token = None
    source.lease = source.lease_until = None
    source.current_lease = source.current_lease_until = None
    source.save()
