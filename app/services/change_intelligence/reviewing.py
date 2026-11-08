"""Manual episode decisions, authorized snapshots and atomic audit history."""

from contextlib import contextmanager
import hashlib
import json

from peewee import DoesNotExist

from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.models import (
    AlertGroup,
    AlertGroupEpisode,
    Change,
    ChangeAlertGroupCorrelation,
    ChangeIntegration,
)
from app.modules.redaction import redact_secrets
from app.services.audit import write_audit
from app.services.change_intelligence import correlation, reading
from app.services.change_intelligence.administration import ChangeConflict, lock_catalog
from app.services.change_intelligence.authorization import lock_row
from app.services.rbac import (
    can_respond_team,
    current_api_token,
    current_user,
    is_admin_user,
)
from app.services.serializers.common import serialize_utc_datetime as timestamp


class ReviewDenied(PermissionError):
    """A readable target requires the existing responder role to modify it."""


class ReviewConflict(ChangeConflict):
    """A review conflict with a stable reason for localized recovery guidance."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def visible_teams(field, teams):
    """Keep token boundaries even when its owner is a global administrator."""
    allowed = field.in_(teams)
    token = current_api_token()
    if is_admin_user() and not (token and (token.group_id or token.team_id)):
        allowed |= field.is_null(True)
    return allowed


def can_respond(target, teams):
    """Reading the Change never grants permission to operate its target."""
    if target.team_id is None:
        token = current_api_token()
        return is_admin_user() and not (token and (token.group_id or token.team_id))
    return target.team_id in teams and can_respond_team(current_user(), target.team_id)


def require_response(target, teams):
    """Reject readers without the target resource's operational role."""
    if not can_respond(target, teams):
        raise ReviewDenied("Responder permission is required for the target")


def visible_change(uid, teams):
    return reading.visible_changes(teams).where(Change.uid == uid).get()


@contextmanager
def change_transaction(uid):
    """Use the worker's lock order before checking current Change visibility."""
    with incident_core_repo.write_transaction():
        lock_catalog()
        initial = Change.get(Change.uid == uid)
        lock_row(
            ChangeIntegration.select().where(
                ChangeIntegration.id == initial.integration_id
            )
        )
        change = lock_row(Change.select().where(Change.id == initial.id))
        teams = reading.reader_teams()
        visible_change(uid, teams)
        yield change, teams


def episode_query(teams):
    return (
        AlertGroupEpisode.select(AlertGroupEpisode)
        .join(AlertGroup)
        .where(visible_teams(AlertGroup.team, teams))
    )


def episode_data(episode):
    """Only serialize after authorizing the owning technical AlertGroup."""
    return {
        "id": episode.id,
        "alert_group_id": episode.alert_group_id,
        "title": episode.alert_group.title,
        "ordinal": episode.ordinal,
        "state": episode.state,
        "started_at": timestamp(episode.started_at),
        "ended_at": timestamp(episode.ended_at),
    }


def lock_episode(episode_id, teams):
    initial = episode_query(teams).where(AlertGroupEpisode.id == episode_id).get()
    incident_core_repo.lock_alert_group(initial.alert_group_id)
    episode = lock_row(
        AlertGroupEpisode.select().where(AlertGroupEpisode.id == episode_id)
    )
    if episode is None:
        raise DoesNotExist()
    episode_query(teams).where(AlertGroupEpisode.id == episode.id).get()
    require_response(episode.alert_group, teams)
    return episode


def suggestion_current(row):
    """A stale stored candidate cannot be confirmed as current evidence."""
    return correlation.is_current_suggestion(row)


def evidence_version(row):
    """Fence automatic recalculation separately from the manual row version."""
    value = {
        "input_stamp": row.input_stamp,
        "evidence": row.evidence,
        "computed_at": timestamp(row.computed_at),
        "score": row.score,
        "reason": row.reason,
        "active": row.active,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def snapshot(row, change, episode, teams, note):
    """Freeze only what the operator can see; do not copy private graph paths."""
    current = row is not None and suggestion_current(row)
    change_view = reading.change_data(change, teams)
    # Mapping diagnostics/counts and Service visibility are current, not evidence.
    change_view = {
        key: value
        for key, value in change_view.items()
        if key
        in {
            "uid",
            "projection",
            "title",
            "kind",
            "occurred_at",
            "source",
            "environment",
            "status",
        }
    }
    return {
        "change": change_view,
        "episode": episode_data(episode),
        "suggestion": {
            "score": row.score if current else None,
            "reason": row.reason if current else "manual",
            "computed_at": timestamp(row.computed_at) if current else None,
            "gap_seconds": row.evidence.get("gap_seconds") if current else None,
            "environment": row.evidence.get("environment") if current else None,
        },
        "note": redact_secrets(note),
        "recorded_at": timestamp(utc_now()),
    }


def review_data(row, teams):
    """Full snapshots never become a way for safe readers to recover private data."""
    evidence = row.review_evidence
    if evidence:
        evidence = dict(evidence)
        stored_change = evidence.get("change", {})
        if (
            row.change.owner_team_id not in teams
            and stored_change.get("projection") == "full"
        ):
            evidence["change"] = {
                "uid": stored_change["uid"],
                "kind": stored_change["kind"],
                "occurred_at": stored_change["occurred_at"],
                "projection": "safe",
                "title": "Related change",
            }
        elif stored_change.get("projection") == "safe":
            # Service access may have changed since the snapshot was recorded.
            evidence["change"] = {
                key: value for key, value in stored_change.items() if key != "services"
            }
    current = suggestion_current(row) if row.review_status == "suggested" else False
    return {
        "id": row.id,
        "episode": episode_data(row.episode),
        "review_status": row.review_status,
        "relation_type": row.relation_type,
        "row_version": row.row_version,
        "score": row.score if current else None,
        "suggestion_current": current,
        "evidence_version": evidence_version(row) if current else None,
        "reviewed_by": row.reviewed_by_id,
        "reviewed_at": timestamp(row.reviewed_at),
        "review_evidence": evidence,
        "can_review": can_respond(row.episode.alert_group, teams),
    }


def correlation_query(change, teams):
    """Apply target visibility in SQL before pagination and counts."""
    return (
        ChangeAlertGroupCorrelation.select()
        .where(
            ChangeAlertGroupCorrelation.change == change.id,
            ChangeAlertGroupCorrelation.episode.in_(
                episode_query(teams).select(AlertGroupEpisode.id)
            ),
        )
        .order_by(ChangeAlertGroupCorrelation.id.desc())
    )


def audit_review(action, row, before):
    group = row.episode.alert_group
    write_audit(
        action,
        object_type="change_correlation",
        object_id=row.id,
        group_id=group.team.group_id if group.team_id else None,
        team_id=group.team_id,
        data={
            "change_uid": str(row.change.uid),
            "episode_id": row.episode_id,
            "before": {
                key: value for key, value in (before or {}).items() if key != "evidence"
            },
            "after": {
                "row_version": row.row_version,
                "review_status": row.review_status,
                "relation_type": row.relation_type,
                "note": row.review_evidence.get("note"),
            },
        },
    )


def create_correlation(uid, payload):
    """Allow manual mitigation/context outside policy and automatic time windows."""
    with change_transaction(uid) as (change, teams):
        episode = lock_episode(payload.episode_id, teams)
        existing = ChangeAlertGroupCorrelation.get_or_none(
            ChangeAlertGroupCorrelation.change == change.id,
            ChangeAlertGroupCorrelation.episode == episode.id,
        )
        if existing:
            raise ReviewConflict(
                "relation_exists",
                "This episode already has a relation; reload and review it",
            )
        row = ChangeAlertGroupCorrelation.create(
            change=change,
            episode=episode,
            score=None,
            reason="manual",
            engine_version="manual",
            active=False,
            review_status="confirmed",
            relation_type=payload.relation_type,
            reviewed_by=current_user().id,
            reviewed_at=utc_now(),
            review_evidence=snapshot(None, change, episode, teams, payload.note),
        )
        audit_review("change.correlation.create", row, None)
        return review_data(row, teams)


def review_correlation(uid, correlation_id, payload):
    """CAS, evidence and audit commit together; workers never overwrite reviews."""
    with change_transaction(uid) as (change, teams):
        row = (
            correlation_query(change, teams)
            .where(ChangeAlertGroupCorrelation.id == correlation_id)
            .get()
        )
        episode = lock_episode(row.episode_id, teams)
        row = lock_row(
            ChangeAlertGroupCorrelation.select().where(
                ChangeAlertGroupCorrelation.id == row.id
            )
        )
        if row.row_version != payload.row_version:
            raise ReviewConflict(
                "relation_changed",
                "This relation was modified; reload before reviewing",
            )
        if (
            row.review_status == "suggested"
            and not payload.manual
            and not suggestion_current(row)
        ):
            raise ReviewConflict(
                "suggestion_stale", "This suggestion is stale; reload before reviewing"
            )
        if (
            row.review_status == "suggested"
            and not payload.manual
            and payload.evidence_version != evidence_version(row)
        ):
            raise ReviewConflict(
                "evidence_changed",
                "The suggestion evidence changed; reload before reviewing",
            )
        before = {
            "row_version": row.row_version,
            "review_status": row.review_status,
            "relation_type": row.relation_type,
            "evidence": row.review_evidence,
        }
        evidence = snapshot(row, change, episode, teams, payload.note)
        # Reconsidering a decision preserves the evidence originally reviewed.
        if row.review_evidence:
            evidence = {**row.review_evidence, "note": redact_secrets(payload.note)}
        changed = (
            ChangeAlertGroupCorrelation.update(
                review_status=payload.decision,
                relation_type=payload.relation_type,
                reviewed_by=current_user().id,
                reviewed_at=utc_now(),
                review_evidence=evidence,
                updated_at=utc_now(),
                row_version=ChangeAlertGroupCorrelation.row_version + 1,
            )
            .where(
                ChangeAlertGroupCorrelation.id == row.id,
                ChangeAlertGroupCorrelation.row_version == payload.row_version,
            )
            .execute()
        )
        if changed != 1:
            raise ReviewConflict(
                "relation_changed",
                "This relation was modified; reload before reviewing",
            )
        row = ChangeAlertGroupCorrelation.get_by_id(row.id)
        audit_review("change.correlation.review", row, before)
        return review_data(row, teams)
