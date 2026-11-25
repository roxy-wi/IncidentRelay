"""Operator assessments of technical AlertGroups."""

from app.modules.common import utc_now
from app.modules.db import alerts_repo, incident_core_repo
from app.modules.db.models import AlertGroupReview, User
from app.modules.db.transactions import write_transaction
from app.modules.user_colors import user_color
from app.services.audit import record_audit
from app.services.authorization import current_authorization, refresh_authority, token_allows_operation
from app.services.incidents import core
from app.services.incidents.stakeholders import notify_stakeholders
from app.services.rbac import can_access_team_or_group_resource, can_read_team, can_respond_team, is_admin_user
from app.services.serializers.common import serialize_utc_datetime


def can_classify(user, team_id):
    """Allow responders and operational editors within their credential bounds."""
    return bool(user and (is_admin_user(user) or (team_id and (
        can_respond_team(user, team_id)
        or can_access_team_or_group_resource(user, team_id, write_required=True)
    ))))


def _token_permits(scope):
    token = current_authorization().token
    return token is None or token_allows_operation(token, [scope])


def _readable(target, user):
    return user is not None and target is not None and (is_admin_user(user) or (
        target.team_id is not None and can_read_team(user, target.team_id)
    ))


def review_data(group, user):
    """Serialize a review, exposing a reference only to readers of its target."""
    review = AlertGroupReview.get_or_none(AlertGroupReview.group == group.id)
    author = review.classified_by if review and review.classified_by_id else None
    group_id = incident_id = None
    if review and review.canonical_group_id and _token_permits("alerts:read") and _readable(review.canonical_group, user):
        group_id = review.canonical_group_id
    if review and review.incident_id and _token_permits("incidents:read") and _readable(review.incident, user):
        incident_id = review.incident_id
    return {
        "version": review.version if review else 0,
        "classification": review.classification if review else None,
        "note": review.note if review else None,
        "classified_by_id": review.classified_by_id if review else None,
        "classified_by": author.username if author else None,
        "classified_by_color": user_color(author),
        "classified_at": serialize_utc_datetime(review.classified_at) if review else None,
        "canonical_group_id": group_id,
        "incident_id": incident_id,
        "can_classify": can_classify(user, group.team_id) and _token_permits("alerts:write"),
    }


def _check_duplicate(group_id, canonical_id, target, actor):
    """Keep a canonical group at the root and reject cycles while its row is locked."""
    if canonical_id:
        if not _token_permits("alerts:read") or not _readable(target, actor):
            raise LookupError("Classification target is unavailable")
        if canonical_id == group_id:
            raise ValueError("An AlertGroup cannot be its own duplicate target")
        if AlertGroupReview.select().where(
            AlertGroupReview.group == canonical_id, AlertGroupReview.classification == "duplicate",
        ).exists():
            raise ValueError("Choose the canonical target of the duplicate")
    if AlertGroupReview.select().where(
        AlertGroupReview.canonical_group == group_id,
    ).exists():
        raise core.IncidentConflictError("Move existing duplicate references before reclassifying their canonical group")


def _record_review(group, review, version, after, actor, api_token_id):
    """Write a changed assessment together with its technical history and audit entry."""
    before = (None, None, None, None) if review is None else (
        review.classification, review.note, review.canonical_group_id, review.incident_id,
    )
    outcome, note, _, _ = after
    if before == after:
        return
    new_review = review is None
    if new_review:
        review = AlertGroupReview(group=group)
    review.classification, review.note, review.canonical_group, review.incident = after
    review.classified_by = actor if outcome else None
    review.classified_at = utc_now() if outcome else None
    review.version = version + 1
    review.save(force_insert=new_review)
    action = "cleared" if outcome is None else ("changed" if before[0] else "set")
    alerts_repo.create_alert_event(
        group_id=group.id, event_type=f"alert_classification_{action}", user_id=actor.id,
        message=f"Classification {action} ({before[0] or '-'} → {outcome or '-'}).",
    )
    record_audit(
        f"alert_group.classification.{action}", "alert_group", group.id,
        group_id=group.team.group_id if group.team_id else None, team_id=group.team_id,
        user_id=actor.id, api_token_id=api_token_id,
        data={"source": "api", "from": before[0], "to": outcome, "version": review.version,
              "note_changed": before[1] != note, "target_changed": before[2:] != after[2:]},
    )


def update_review(group_id, *, expected_version, update=None):
    """Commit the assessment, optional Incident link, timeline and audit as one operation."""
    canonical_id = update.canonical_group_id if update else None
    incident_id = update.incident_id if update else None
    outcome = update.classification if update else None
    note = (update.note or None) if update else None
    created = None
    with write_transaction():
        # Incident links take the Incident lock before locking their AlertGroup.
        incident = incident_core_repo.lock_incident(incident_id) if incident_id else None
        authority = refresh_authority(lock=True)
        actor = User.get_or_none(User.id == getattr(authority.user, "id", None),
                                 User.active == True, User.deleted == False)  # noqa: E712
        groups = {pk: incident_core_repo.lock_alert_group(pk)
                  for pk in sorted({group_id, canonical_id} - {None})}
        group = groups[group_id]
        if group is None:
            raise LookupError("AlertGroup not found")
        if not can_classify(actor, group.team_id):
            raise PermissionError("Permission to classify this AlertGroup is required")

        review = AlertGroupReview.get_or_none(AlertGroupReview.group == group.id)
        if expected_version != (review.version if review else 0):
            raise core.IncidentConflictError("Classification changed. Reload the AlertGroup before saving.")
        if incident_id and (not _token_permits("incidents:read") or not _readable(incident, actor)):
            raise LookupError("Classification target is unavailable")
        if outcome == "duplicate":
            _check_duplicate(group_id, canonical_id, groups.get(canonical_id), actor)

        actor_info = {"user_id": actor.id, "api_token_id": getattr(authority.token, "id", None), "source": "api"}
        keep_incident = bool(review and review.classification == "incident" and review.incident_id == incident_id)
        if outcome == "incident" and (update.create_incident or (incident_id and not keep_incident)):
            if not (is_admin_user(actor) or (group.team_id and can_respond_team(actor, group.team_id))):
                raise PermissionError("Team responder permission is required to link an Incident")
            if update.create_incident:
                if incident_core_repo.active_link_for_group(group.id):
                    raise core.IncidentConflictError("This AlertGroup already has an open Incident")
                created = core.create_incident_from_alert_group(
                    group.id, title=group.title[:255], notify=False, **actor_info,
                )
                incident_id = created.id
            else:
                if not _token_permits("incidents:write"):
                    raise PermissionError("Incident write permission is required to link an Incident")
                if incident.team_id != group.team_id:
                    raise ValueError("Select an Incident in the AlertGroup team")
                core.link_alert_group(incident_id, group.id, user=actor, **actor_info)

        _record_review(group, review, expected_version, (outcome, note, canonical_id, incident_id),
                       actor, actor_info["api_token_id"])
        result = review_data(group, actor)
    if created is not None:
        notify_stakeholders(created, "created", skip_user_id=actor.id)
    return result
