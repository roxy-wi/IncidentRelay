"""Preview, fenced execution, retries and scheduling for directory sources."""

import hashlib
import json
import uuid
from datetime import timedelta

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.crypto import decrypt_json, encrypt_json
from app.modules.db.models import (
    AppLock, DirectorySyncBinding as Binding, DirectorySyncCurrent as Current,
    DirectorySyncSource as Source, Group, User, UserGroup,
)
from app.modules.db.transactions import lock_row, write_transaction
from app.services.sync.directory.client import ApiClient
from app.services.sync.directory.config import SyncBusy, SyncConfig, SyncError, current_api_enabled
from app.services.sync.directory.diagnostics import error_message, log_failure, logged_operation
from app.services.sync.directory.fetch import fetch_current, fetch_snapshot, instant
from app.services.sync.directory.reconcile import reconcile


def authorized_actor(actor_id, group_id):
    """Recheck active ownership for requests and background runs."""
    def row(query):
        return lock_row(query) if db.in_transaction() else query.first()
    user = row(User.select().where(User.id == actor_id, User.active == True, User.deleted == False))
    group = row(Group.select().where(Group.id == group_id, Group.active == True, Group.deleted == False))
    return bool(user and group and (user.is_admin or row(UserGroup.select().where(
        UserGroup.user == actor_id, UserGroup.group == group_id,
        UserGroup.role == "user_admin", UserGroup.active == True,
    ))))


def has_pending_preview(source, now=None):
    """Keep a prepared plan available until it is applied or expires."""
    return bool(source.preview_token and source.preview_until
                and source.preview_until > (now or utc_now()))


def claim(source_id, *, current=False, scheduled=False):
    """CAS lease shared by manual execution, previews and all scheduler processes."""
    now, token = utc_now(), str(uuid.uuid4())
    lease = Source.current_lease if current else Source.lease
    until = Source.current_lease_until if current else Source.lease_until
    query = Source.update({lease: token, until: now + timedelta(seconds=180)}).where(
        Source.id == source_id, Source.deleted == False, (lease.is_null()) | (until <= now),
    )
    if scheduled:
        query = query.where(Source.approved_revision == Source.revision)
        if current:
            query = query.where(
                Source.last_success_at.is_null(False), Source.next_current_at <= now,
                (Source.enabled == True)
                | ((Source.last_current_at.is_null() | (Source.last_current_at < Source.last_success_at))
                   & (Source.next_current_at <= Source.last_success_at)),
            )
        else:
            query = query.where(
                Source.enabled == True, Source.next_run_at <= now, Source.pending_mode.is_null(),
                Source.preview_token.is_null() | Source.preview_until.is_null() | (Source.preview_until <= now),
            )
    changed = query.execute()
    if not changed:
        raise SyncBusy("Synchronization is already running")
    return token


def heartbeat(source_id, token, *, current=False):
    """Extend only a still-live lease; an expired worker cannot reclaim it."""
    now = utc_now()
    lease = Source.current_lease if current else Source.lease
    until = Source.current_lease_until if current else Source.lease_until
    if not Source.update({until: now + timedelta(seconds=180)}).where(
        Source.id == source_id, Source.deleted == False, lease == token, until > now,
    ).execute():
        raise SyncError("Synchronization lease expired")


def locked_source(source_id, token, revision, *, current=False):
    source = lock_row(Source.select().where(Source.id == source_id))
    lease = source.current_lease if current and source else getattr(source, "lease", None)
    until = source.current_lease_until if current and source else getattr(source, "lease_until", None)
    if (not source or source.deleted or lease != token or not until or until <= utc_now()
            or source.revision != revision):
        raise SyncError("Configuration or synchronization lease changed; fetch a new preview")
    if not authorized_actor(source.created_by_id, source.group_id):
        raise SyncError("Source owner no longer administers the destination group")
    return source


def apply_lock():
    """Serialize identity matching between sources across all application workers."""
    AppLock.get_or_create(name="directory_sync_catalog", defaults={
        "owner": "directory_sync", "expires_at": utc_now(), "updated_at": utc_now(),
    })
    lock_row(AppLock.select().where(AppLock.name == "directory_sync_catalog"))


def digest(value):
    """Compare plans independently of query order and worker hash randomization."""
    rows = sorted(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in value)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


@logged_operation("sync")
def run(source_id, *, mode="run", preview_token=None, scheduled=False):
    """Fetch outside transactions, then preview/apply one complete snapshot atomically."""
    from app.services.sync.cmdb.config import is_cmdb

    if is_cmdb(Source.get_by_id(source_id).config):
        from app.services.sync.cmdb.execution import run as run_catalog
        return run_catalog(source_id, mode=mode, preview_token=preview_token, scheduled=scheduled)
    token = claim(source_id, scheduled=scheduled)
    client = None
    retry_interval = SyncConfig.model_fields["interval_seconds"].default
    try:
        source = Source.get_by_id(source_id)
        config = SyncConfig.model_validate(source.config)
        retry_interval = config.interval_seconds
        if not authorized_actor(source.created_by_id, source.group_id):
            raise SyncError("Source owner no longer administers the destination group")
        client = ApiClient(config, decrypt_json(source.headers_encrypted, default={}),
                           heartbeat=lambda: heartbeat(source_id, token))
        saved = None
        if mode == "apply":
            if (not preview_token or source.preview_token != preview_token
                    or not source.preview_until or source.preview_until <= utc_now()):
                raise SyncError("Preview expired; fetch a new preview")
            saved = decrypt_json(source.preview_encrypted)
            if saved["revision"] != source.revision:
                raise SyncError("Configuration changed; fetch a new preview")
            snapshot = saved["snapshot"]
        else:
            snapshot = fetch_snapshot(client)
        heartbeat(source_id, token)
        with write_transaction():
            source = locked_source(source_id, token, source.revision)
            apply_lock()
            if mode == "preview":
                with db.atomic() as preview:
                    changes = reconcile(source, snapshot)
                    preview.rollback()
                result = {"changes": changes, "from": snapshot["from"], "to": snapshot["to"],
                          "teams": len(snapshot["teams"]), "users": len(snapshot["users"]),
                          "team_catalog": [{"id": team["id"], "name": team["name"]} for team in snapshot["teams"]],
                          "samples": client.samples}
                source.preview_token = str(uuid.uuid4())
                source.preview_until = utc_now() + timedelta(minutes=15)
                source.preview_encrypted = encrypt_json({"snapshot": snapshot, "revision": source.revision,
                                                         "plan": digest(changes)})
                source.preview_result = result
                source.last_error = None
                source.save(only=[Source.preview_token, Source.preview_until, Source.preview_encrypted,
                                  Source.preview_result, Source.last_error])
                return {**result, "preview_token": source.preview_token}
            changes = reconcile(source, snapshot)
            if saved and saved["plan"] != digest(changes):
                raise SyncError("Local data changed since preview; fetch a new preview")
            now = utc_now()
            source.last_success_at = now
            source.approved_revision = source.revision
            source.last_error = None
            source.last_result = {"teams": len(snapshot["teams"]), "users": len(snapshot["users"]),
                                  "changes": len(changes), "from": snapshot["from"], "to": snapshot["to"],
                                  "schedule_ids": [s["id"] for team in snapshot["teams"] for s in team["schedules"]]}
            source.next_run_at = now + timedelta(seconds=config.interval_seconds)
            # Periodic imports must not shorten the independent duty interval.
            # Explicit imports still request an immediate check of the new data.
            if not scheduled:
                source.next_current_at = now
            source.preview_encrypted = None
            source.preview_token = None
            source.preview_until = None
            source.save(only=[Source.last_success_at, Source.approved_revision, Source.last_error, Source.last_result,
                              Source.next_run_at, Source.next_current_at, Source.preview_encrypted,
                              Source.preview_token, Source.preview_until])
            from app.services.audit import record_audit
            record_audit("directory_sync.apply", object_type="directory_sync", object_id=source.id,
                         group_id=source.group_id, user_id=source.created_by_id,
                         data=source.last_result, transport="system")
            return {**source.last_result, "changes": changes}
    except Exception as error:
        # Exceptions may embed credentials/URLs/response bodies; store only our
        # controlled errors or an exception type. Never log upstream exception text.
        message = error_message(error, "Synchronization failed")
        Source.update(last_error=message, next_run_at=utc_now() + timedelta(seconds=retry_interval)).where(
            Source.id == source_id, Source.lease == token,
        ).execute()
        if mode == "preview" and client:
            Source.update(preview_result={"samples": client.samples, "changes": []},
                          preview_token=None, preview_encrypted=None).where(
                Source.id == source_id, Source.lease == token,
            ).execute()
        if isinstance(error, SyncError):
            raise
        raise SyncError(message) from error
    finally:
        Source.update(lease=None, lease_until=None).where(Source.id == source_id, Source.lease == token).execute()


@logged_operation("current")
def refresh_current(source_id, *, scheduled=False):
    """Refresh authoritative duty separately; stale cached answers never assign users."""
    token = claim(source_id, current=True, scheduled=scheduled)
    needs_full_sync = False
    revision = None
    # Keep failure handling usable if the persisted configuration is invalid.
    retry_interval = SyncConfig.model_fields["current_interval_seconds"].default
    try:
        source = Source.get_by_id(source_id)
        revision = source.revision
        config = SyncConfig.model_validate(source.config)
        retry_interval = config.current_interval_seconds
        if not current_api_enabled(source.config):
            return
        rotations = {b.external_id: b.local_id for b in Binding.select().where(
            Binding.source == source.id, Binding.kind == "rotation", Binding.owned == True, Binding.present == True,
        )}
        rotations = {key: value for key, value in rotations.items() if key in source.last_result.get("schedule_ids", [])}
        client = ApiClient(config, decrypt_json(source.headers_encrypted, default={}),
                           heartbeat=lambda: heartbeat(source_id, token, current=True))
        rows = fetch_current(client, list(rotations))
        status_failures = []
        with write_transaction():
            source = locked_source(source_id, token, source.revision, current=True)
            users = {b.external_id: b.local_id for b in Binding.select().where(
                Binding.source == source.id, Binding.kind == "user", Binding.present == True,
            )}
            now = utc_now()
            for row in rows:
                if row.get("_status_error"):
                    rotation_id = rotations[row["id"]]
                    status_failures.append((rotation_id, row["_status_error"]))
                    # A malformed answer must not leave this slot assigned to
                    # the previous person while healthy slots are refreshed.
                    Current.delete().where(Current.source == source.id, Current.rotation == rotation_id).execute()
                    continue
                if row["status"] == "active" and row["user_id"] not in users:
                    needs_full_sync = True
                    raise SyncError("Current duty references a new person; a full synchronization is required")
                expires = now + timedelta(seconds=config.current_max_age_seconds)
                if row.get("valid_until"):
                    expires = min(instant(row["valid_until"]), expires)
                if row.get("end"):
                    expires = min(expires, instant(row["end"]))
                if expires <= now:
                    raise SyncError("Current duty response has already expired")
                if row.get("start") and instant(row["start"]) > now:
                    raise SyncError("Current duty starts in the future")
                values = {"source": source.id, "rotation": rotations[row["id"]],
                          "user": users.get(row.get("user_id")) if row["status"] == "active" else None,
                          "status": row["status"], "observed_at": now, "valid_until": expires}
                old = Current.get_or_none(Current.rotation == rotations[row["id"]])
                if old:
                    Current.update(**values).where(Current.id == old.id).execute()
                else:
                    Current.create(**values)
            # Cache expiry controls whether an answer is usable, not polling frequency.
            updates = {"next_current_at": now + timedelta(seconds=config.current_interval_seconds)}
            if status_failures:
                rotation_id, first_error = status_failures[0]
                partial_message = (
                    f"Current duty updated for {len(rows) - len(status_failures)} of {len(rows)} schedules; "
                    f"{len(status_failures)} failed. Rotation {rotation_id}: {first_error}"
                )
                updates["current_error"] = partial_message
            else:
                updates.update(last_current_at=now, current_error=None)
            Source.update(**updates).where(
                Source.id == source.id,
            ).execute()
        if status_failures:
            for rotation_id, error in status_failures:
                log_failure(error, source_id=source_id, operation="current.status", rotation_id=rotation_id)
            # Report the partial result only after committing healthy answers.
            raise SyncError(partial_message)
    except Exception as error:
        message = error_message(error, "Current duty refresh failed")
        updates = {"current_error": message, "next_current_at": utc_now() + timedelta(seconds=retry_interval)}
        # Transport/response errors cannot be repaired by importing the catalog.
        # A new person warrants one early import; if it does not resolve the
        # problem, preserve the full-sync interval until current duty recovers.
        if needs_full_sync and not source.current_error:
            updates["next_run_at"] = utc_now()
        Source.update(**updates).where(
            Source.id == source_id, Source.current_lease == token, Source.revision == revision,
        ).execute()
        raise SyncError(message) from error
    finally:
        Source.update(current_lease=None, current_lease_until=None).where(Source.id == source_id, Source.current_lease == token).execute()


def process_due_sources():
    """Execute due work; each source has its own fenced cross-process lease."""
    count = 0
    Source.update(preview_encrypted=None, preview_token=None, preview_result=None, preview_until=None).where(
        Source.preview_until < utc_now(), Source.pending_mode.is_null(), Source.lease.is_null(),
    ).execute()
    # Finish the read before per-source transactions can invalidate its cursor.
    sources = list(Source.select().where(
        Source.deleted == False, (Source.enabled == True) | Source.pending_mode.is_null(False),
    ).order_by(Source.next_current_at))
    for source in sources:
        if source.lease and source.lease_until and source.lease_until > utc_now():
            continue
        try:
            if source.pending_mode:
                mode = source.pending_mode
                try:
                    run(source.id, mode=mode, preview_token=source.pending_preview_token)
                except SyncBusy:
                    continue
                except SyncError:
                    Source.update(pending_mode=None, pending_preview_token=None).where(
                        Source.id == source.id, Source.pending_mode == mode, Source.lease.is_null(),
                    ).execute()
                    raise
                Source.update(pending_mode=None, pending_preview_token=None).where(
                    Source.id == source.id, Source.pending_mode == mode, Source.lease.is_null(),
                ).execute()
                if mode in {"preview", "inspect"}:
                    continue
                count += 1
            elif (source.enabled and source.approved_revision == source.revision
                    and source.next_run_at <= utc_now() and not has_pending_preview(source)):
                run(source.id, scheduled=True)
                count += 1
        except SyncError:
            # Failure is already persisted per source; another source may proceed.
            continue
    return count


def process_due_current():
    """Current duty refresh has its own scheduler job and per-source lease."""
    count = 0
    # A failed refresh rolls back; do not leave the scheduler's read cursor open.
    sources = list(Source.select().where(
        Source.deleted == False, Source.last_success_at.is_null(False),
        Source.approved_revision == Source.revision, Source.next_current_at <= utc_now(),
    ))
    for source in sources:
        if not current_api_enabled(source.config):
            continue
        # Disabling periodic synchronization also stops authoritative polling.
        # Import sets next_current_at to last_success_at. Every completed attempt
        # advances it, including failures, so a paused source gets one check only.
        if not source.enabled and (
            source.next_current_at > source.last_success_at
            or (source.last_current_at and source.last_current_at >= source.last_success_at)
        ):
            continue
        try:
            refresh_current(source.id, scheduled=True)
            count += 1
        except SyncError:
            continue
    return count
