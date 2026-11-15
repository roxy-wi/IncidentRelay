"""Atomic Change intake, with credential rechecks and deterministic retries."""

import hashlib
import json
import random
import time
from contextlib import contextmanager
from datetime import timedelta

from peewee import OperationalError, SqliteDatabase

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import Change, ChangeEvent, ChangeIntegration, ChangeSource, Team
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
from app.services.system_settings import get_settings


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
    digest = _content_digest(content)
    return _retry_intake(lambda: _ingest_once(payload, content, digest, raw_token))


def _content_digest(content):
    return hashlib.sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _retry_intake(operation):
    for attempt in range(3):
        try:
            return operation()
        except OperationalError as error:
            if not _transient(error):
                raise
            if attempt == 2:
                raise ChangeIntakeBusy(
                    "Change intake is busy; retry the same event"
                ) from error
            time.sleep(random.uniform(0.02, 0.06) * (2**attempt))


@contextmanager
def _intake_transaction(raw_token):
    """Serialize routing and authority edits with all writes and their retries."""
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
        yield token


def _existing_event(source, event_id, digest):
    existing = ChangeEvent.get_or_none(
        ChangeEvent.source == source.id,
        ChangeEvent.external_event_id == event_id,
    )
    if existing:
        if existing.request_digest != digest:
            raise ChangeEventConflict("event_id was already used with different content")
        return _result(existing, existing.change, get_settings().change_worker_enabled), False
    return None


def ingest_gitlab_event(payload, raw_token, source_id):
    """Map native deployments under the same lock used for permission edits.

    The digest describes sender content, independently of mutable mappings.
    A redelivery never remaps an already accepted event or increments revisions.
    """
    content = payload.model_dump(mode="json")
    digest = _content_digest({"gitlab_deployment": content})
    event_id = "gitlab:" + _content_digest([
        payload.project.id, payload.deployment_id, payload.status,
        payload.status_changed_at.isoformat(),
    ])

    def accept():
        with _intake_transaction(raw_token) as token:
            configured = ChangeSource.get_or_none(
                ChangeSource.id == source_id,
                ChangeSource.integration == token.change_integration_id,
            )
            if configured is None:
                raise ChangeAccessDenied("Change access denied")
            with authorized_source(
                token.change_integration_id, configured.owner_team_id,
                configured.source, raw_token=raw_token,
            ) as (source, _revision):
                existing = _existing_event(source, event_id, digest)
                if existing:
                    return existing
                mapping = next((
                    row for row in source.gitlab_mappings
                    if row["project_id"] == payload.project.id
                    and row["environment"] == payload.environment
                ), None)
                if mapping is None:
                    return {"status": "ignored", "reason": "no_matching_mapping"}, False
                if source.ordering_mode != "timestamp":
                    raise InvalidChangeInput("GitLab webhooks require timestamp ordering")
                event = payload.change_event(source, mapping["service_ids"], event_id)
                return _ingest_once(event, event.submitted_content(), digest, raw_token)

    return _retry_intake(accept)


def _ingest_once(payload, content, digest, raw_token):
    with _intake_transaction(raw_token) as token:
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
            settings = get_settings()
            existing = _existing_event(source, payload.event_id, digest)
            if existing:
                return existing
            now = utc_now()
            occurred_at = payload.occurred_at.replace(tzinfo=None)
            if occurred_at > now + timedelta(
                seconds=settings.change_max_future_seconds
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
                .limit(settings.change_events_per_minute)
            )
            if recent.count() >= settings.change_events_per_minute:
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
                >= settings.change_events_per_change
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
                        change, event, source, relation, reference, auth_revision,
                        ttl_seconds=settings.change_pending_ttl_seconds,
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
            return _result(event, Change.get_by_id(change.id), settings.change_worker_enabled), True


def _result(event, change, worker_enabled):
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
        "correlation_status": "queued" if worker_enabled else "not_enabled",
    }
