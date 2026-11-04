"""Atomic Change intake, with credential rechecks and deterministic retries."""

import hashlib
import json
import random
import time
from datetime import timedelta

from peewee import OperationalError, SqliteDatabase

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import Change, ChangeEvent, ChangeIntegration, Team
from app.modules.redaction import redact_secrets
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    authorized_source,
    find_machine_token,
    lock_row,
)
from app.services.change_intelligence.projection import (
    PROJECTION_FIELDS,
    project_events,
)
from app.services.change_intelligence.references import (
    InvalidChangeInput,
    mapping_summary,
    resolve_reference,
)
from app.settings import Config


class ChangeEventConflict(ValueError):
    """An event, operation identity or sequence was reused incompatibly."""


class ChangeRateLimited(RuntimeError):
    """The integration's rolling accepted-event quota has been reached."""


class ChangeIntakeBusy(RuntimeError):
    """Transient contention persisted beyond the bounded retry budget."""


def _transient(error):
    original = (
        getattr(error, "orig", None) or error.__cause__ or error.__context__ or error
    )
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return code in {"40001", "40P01", "55P03", "57014"} or (
        isinstance(db.obj, SqliteDatabase)
        and str(error).lower() in {"database is locked", "database table is locked"}
    )


def ingest_event(payload, raw_token):
    """Retry only rolled-back transient database failures, at most three times."""
    content = payload.submitted_content()
    digest = hashlib.sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    for attempt in range(3):
        try:
            return _ingest_once(payload, content, digest, raw_token)
        except OperationalError as error:
            if not _transient(error):
                raise
            if attempt == 2:
                raise ChangeIntakeBusy(
                    "Change intake is busy; retry the same event"
                ) from error
            time.sleep(random.uniform(0.02, 0.06) * (2**attempt))


def _ingest_once(payload, content, digest, raw_token):
    with incident_core_repo.write_transaction():
        if not isinstance(db.obj, SqliteDatabase):
            db.execute_sql("SET LOCAL lock_timeout = '2s'")
            db.execute_sql("SET LOCAL statement_timeout = '5s'")
        token = find_machine_token(raw_token)
        if token is None:
            raise ChangeAccessDenied("Change access denied")
        # Take the integration lock before resolving mutable owner slugs. All
        # admin/catalog writers take this same lock before changing authority.
        lock_row(
            ChangeIntegration.select().where(
                ChangeIntegration.id == token.change_integration_id
            )
        )
        owner = Team.get_or_none(
            Team.id == payload.owner_team_id
            if payload.owner_team_id is not None
            else Team.slug == payload.owner_team_slug
        )
        if owner is None:
            raise ChangeAccessDenied("Change access denied")
        with authorized_source(
            token.change_integration_id, owner.id, payload.source, raw_token=raw_token
        ) as (source, auth_revision):
            existing = ChangeEvent.get_or_none(
                ChangeEvent.source == source.id,
                ChangeEvent.external_event_id == payload.event_id,
            )
            if existing:
                if existing.request_digest != digest:
                    raise ChangeEventConflict(
                        "event_id was already used with different content"
                    )
                return _result(existing, existing.change), False
            now = utc_now()
            occurred_at = payload.occurred_at.replace(tzinfo=None)
            if occurred_at > now + timedelta(
                seconds=Config.CHANGE_EVENTS_MAX_FUTURE_SECONDS
            ):
                raise InvalidChangeInput(
                    "occurred_at exceeds the allowed future clock skew"
                )
            recent = (
                ChangeEvent.select(ChangeEvent.id)
                .where(
                    ChangeEvent.integration == token.change_integration_id,
                    ChangeEvent.received_at >= now - timedelta(minutes=1),
                )
                .limit(Config.CHANGE_EVENTS_PER_MINUTE)
            )
            if len(list(recent)) >= Config.CHANGE_EVENTS_PER_MINUTE:
                raise ChangeRateLimited("Integration event rate exceeded")
            change = lock_row(
                Change.select().where(
                    Change.source == source.id,
                    Change.external_change_id == payload.change_id,
                )
            )
            if change and (
                change.kind != payload.kind or change.environment != payload.environment
            ):
                raise ChangeEventConflict(
                    "kind and environment are immutable for a change_id"
                )
            mode = change.ordering_mode if change else source.ordering_mode
            if (mode == "sequence") != (payload.source_sequence is not None):
                raise InvalidChangeInput(
                    "source_sequence must be supplied only for sequence ordering"
                )
            if (
                change
                and payload.source_sequence is not None
                and ChangeEvent.select()
                .where(
                    ChangeEvent.change == change.id,
                    ChangeEvent.source_sequence == payload.source_sequence,
                )
                .exists()
            ):
                raise ChangeEventConflict(
                    "source_sequence was already used by another event"
                )
            if (
                change
                and ChangeEvent.select().where(ChangeEvent.change == change.id).count()
                >= Config.CHANGE_EVENTS_PER_CHANGE
            ):
                raise InvalidChangeInput("Change event history limit reached")
            if change is None:
                change = Change.create(
                    source=source.id,
                    integration=source.integration_id,
                    owner_team=owner.id,
                    external_change_id=payload.change_id,
                    kind=payload.kind,
                    environment=payload.environment,
                    title=redact_secrets(payload.title or payload.change_id)[:500],
                    ordering_mode=mode,
                )
            else:
                change.revision += 1
            safe = redact_secrets(content)
            # Redaction can expand a short secret into a longer marker. Respect
            # PostgreSQL column limits after redaction as well as before it.
            for name, limit in (("title", 500), ("external_url", 2048)):
                if safe.get(name) is not None:
                    safe[name] = safe[name][:limit]
            if safe.get("actor"):
                safe["actor"]["type"] = safe["actor"]["type"][:64]
                safe["actor"]["name"] = safe["actor"]["name"][:255]
            event = ChangeEvent.create(
                change=change.id,
                source=source.id,
                integration=source.integration_id,
                external_event_id=payload.event_id,
                event_type=payload.event_type,
                occurred_at=occurred_at,
                received_at=now,
                source_sequence=payload.source_sequence,
                actor_type=safe.get("actor", {}).get("type"),
                actor_label=safe.get("actor", {}).get("name"),
                details=safe.get("details", {}),
                projection_fields={
                    name: safe[name] for name in PROJECTION_FIELDS if name in safe
                },
                submitted_references=[
                    {"relation_type": relation, **ref}
                    for relation, name in (
                        ("changed", "changed_services"),
                        ("reported_affected", "affected_services"),
                    )
                    for ref in safe[name]
                ],
                request_snapshot=safe,
                request_digest=digest,
                ingest_token=token.id,
            )
            for relation, name in (
                ("changed", "changed_services"),
                ("reported_affected", "affected_services"),
            ):
                for reference in content[name]:
                    resolve_reference(
                        change, event, source, relation, reference, auth_revision
                    )
            events = list(
                ChangeEvent.select(
                    ChangeEvent.event_type,
                    ChangeEvent.external_event_id,
                    ChangeEvent.occurred_at,
                    ChangeEvent.source_sequence,
                    ChangeEvent.projection_fields,
                ).where(ChangeEvent.change == change.id)
            )
            values = project_events(
                events, mode, redact_secrets(change.external_change_id)[:500]
            )
            values.update(
                mapping_status=mapping_summary(change.id)[0],
                revision=change.revision,
                updated_at=now,
            )
            Change.update(**values).where(Change.id == change.id).execute()
            changes_repo.request_job(
                "resolve_references", change.id, target_revision=change.revision
            )
            return _result(event, Change.get_by_id(change.id)), True


def _result(event, change):
    """A machine credential receives acknowledgements, not a Change read API."""
    return {
        "event_uid": str(event.uid),
        "change_uid": str(change.uid),
        "event_id": event.external_event_id,
        "change_id": change.external_change_id,
        "revision": change.revision,
        "status": change.status,
        "lifecycle_conflict": change.lifecycle_conflict,
        "mapping_status": change.mapping_status,
        "references": mapping_summary(change.id)[1],
        "correlation_status": "queued" if Config.CHANGE_WORKER_ENABLED else "not_enabled",
    }
