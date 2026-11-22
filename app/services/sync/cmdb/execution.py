"""Catalog execution under the shared source lease and preview approval fence."""

import uuid
from datetime import timedelta

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.crypto import decrypt_json, encrypt_json
from app.modules.db.models import DirectorySyncSource as Source
from app.modules.db.transactions import write_transaction
from app.services.sync.cmdb.config import CmdbConfig
from app.services.sync.cmdb.fetch import fetch_snapshot
from app.services.sync.cmdb.reconcile import reconcile
from app.services.sync.directory.client import ApiClient
from app.services.sync.directory.config import SyncError
from app.services.sync.directory.diagnostics import error_message


def run(source_id, *, mode="run", preview_token=None, scheduled=False):
    """Fetch first, then atomically validate/apply the complete catalog snapshot."""
    from app.services.sync.directory.service import (
        apply_lock, authorized_actor, claim, digest, heartbeat, locked_source,
    )

    token = claim(source_id, scheduled=scheduled)
    retry_interval = 3600
    try:
        source = Source.get_by_id(source_id)
        config = CmdbConfig.model_validate(source.config)
        retry_interval = config.interval_seconds
        if not authorized_actor(source.created_by_id, source.group_id):
            raise SyncError("Source owner no longer administers the destination group")
        client = ApiClient(config, decrypt_json(source.headers_encrypted, default={}), heartbeat=lambda: heartbeat(source_id, token))
        saved = None
        if mode == "apply":
            if (not preview_token or source.preview_token != preview_token or not source.preview_until
                    or source.preview_until <= utc_now()):
                raise SyncError("Preview expired; fetch a new preview")
            saved = decrypt_json(source.preview_encrypted)
            if saved["revision"] != source.revision:
                raise SyncError("Configuration changed; fetch a new preview")
            snapshot = saved["snapshot"]
        else:
            snapshot = fetch_snapshot(client, inspect_only=mode == "inspect")
        heartbeat(source_id, token)
        with write_transaction():
            source = locked_source(source_id, token, source.revision)
            apply_lock()
            summary = {"services": len(snapshot["services"]), "business_services": len(snapshot["business_services"]),
                       "attributes": snapshot["attributes"], "team_catalog": snapshot["team_catalog"]}
            if mode in {"preview", "inspect"}:
                with db.atomic() as preview:
                    result = reconcile(source, snapshot) if mode == "preview" else {"changes": [], "issues": snapshot["issues"]}
                    preview.rollback()
                result = {**summary, **result, "inspection": mode == "inspect"}
                ready = mode == "preview" and not result["issues"]
                source.preview_token = str(uuid.uuid4()) if ready else None
                source.preview_until = utc_now() + timedelta(minutes=15) if ready else None
                source.preview_encrypted = encrypt_json({"snapshot": snapshot, "revision": source.revision,
                                                         "plan": digest(result["changes"])}) if ready else None
                source.preview_result = result
                source.last_error = None
                source.save(only=[Source.preview_token, Source.preview_until, Source.preview_encrypted,
                                  Source.preview_result, Source.last_error])
                return {**result, "preview_token": source.preview_token}
            result = reconcile(source, snapshot)
            if result["issues"]:
                raise SyncError("Catalog team or field mappings need attention; inspect the source and create a new preview")
            if saved and saved["plan"] != digest(result["changes"]):
                raise SyncError("Local data changed since preview; fetch a new preview")
            source.last_success_at = utc_now()
            source.next_run_at = source.last_success_at + timedelta(seconds=config.interval_seconds)
            source.last_result = {"services": summary["services"], "business_services": summary["business_services"],
                                  "changes": len(result["changes"]), "warnings": result.get("warnings", [])}
            source.approved_revision = source.revision
            source.last_error = None
            source.preview_token = source.preview_until = source.preview_encrypted = None
            source.preview_result = {**summary, **result, "inspection": False}
            source.save()
            from app.services.audit import record_audit
            record_audit("directory_sync.apply", object_type="directory_sync", object_id=source.id,
                         group_id=source.group_id, user_id=source.created_by_id, data=source.last_result, transport="system")
            return {**source.last_result, "changes": result["changes"]}
    except Exception as error:
        message = error_message(error, "Catalog synchronization failed")
        updates = {"last_error": message, "next_run_at": utc_now() + timedelta(seconds=retry_interval)}
        if mode in {"preview", "inspect"}:
            updates.update(preview_token=None, preview_encrypted=None, preview_until=None)
        Source.update(**updates).where(Source.id == source_id, Source.lease == token).execute()
        if isinstance(error, SyncError):
            raise
        raise SyncError(message) from error
    finally:
        Source.update(lease=None, lease_until=None).where(Source.id == source_id, Source.lease == token).execute()
