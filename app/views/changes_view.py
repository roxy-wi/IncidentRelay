"""Authenticated human Change reads with consistent snapshot visibility."""

from flask import Blueprint, jsonify, request
from peewee import DoesNotExist
from pydantic import ValidationError

from app.api.schemas.base import EmptySchema
from app.api.schemas.changes import ChangePageQuery, ChangeQuery, InvalidChangeQuery
from app.api.schemas.change_reviews import (
    AlertRelatedChangesQuery,
    CorrelationCreate,
    CorrelationReview,
    IncidentChangeCreate,
    IncidentChangeQuery,
    IncidentChangeRemove,
    IncidentChangeUpdate,
    ReviewTargetQuery,
)
from app.modules.db.models import (
    AlertGroup,
    AlertGroupEpisode,
    Change,
    ChangeEvent,
    ChangeAlertGroupCorrelation,
    Incident,
)
from app.services.change_intelligence import incident_links, reading, reviewing
from app.services.change_intelligence.eligibility import episode_eligibility
from app.services.change_intelligence.administration import ChangeConflict
from app.services.validation import make_error_response, validate_body

changes_bp = Blueprint("changes_api", __name__)


@changes_bp.before_request
def require_reader():
    """The experimental read API never becomes public with optional global auth."""
    user = getattr(request, "current_user", None)
    if not user or not user.active:
        return make_error_response(
            "authentication_required", "Authentication is required", 401
        )


@changes_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@changes_bp.errorhandler(DoesNotExist)
def missing(_error):
    return make_error_response("not_found", "Change or related resource not found", 404)


@changes_bp.errorhandler(ChangeConflict)
def conflicting(error):
    return make_error_response("conflict", str(error), 409)


@changes_bp.errorhandler(reviewing.ReviewConflict)
def review_conflicting(error):
    return make_error_response("conflict", str(error), 409, reason=error.reason)


@changes_bp.errorhandler(reviewing.ReviewDenied)
def review_denied(error):
    return make_error_response("forbidden", str(error), 403)


@changes_bp.errorhandler(InvalidChangeQuery)
def invalid(_error):
    return make_error_response(
        "validation_error", "Invalid Change query parameters", 400
    )


def query_input(schema):
    """Reject duplicate selectors, unknown keys and malformed bounded values."""
    if any(len(values) != 1 for _, values in request.args.lists()):
        raise InvalidChangeQuery("Duplicate query parameter")
    try:
        return schema.model_validate(request.args.to_dict())
    except ValidationError as error:
        raise InvalidChangeQuery("Invalid query") from error


@changes_bp.get("/changes")
@changes_bp.get("/services/<int:service_id>/changes")
def list_changes(service_id=None):
    filters = query_input(ChangeQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        query = reading.filter_changes(filters, teams, service_id=service_id)
        return jsonify(reading.changes_page(query, filters, teams))


@changes_bp.get("/changes/sources")
def sources():
    """Offer filter values without exposing integration administration details."""
    query_input(EmptySchema)
    with reading.read_snapshot():
        return jsonify({"items": reading.source_names(reading.reader_teams())})


@changes_bp.get("/changes/<uuid:change_uid>")
def detail(change_uid):
    with reading.read_snapshot():
        teams = reading.reader_teams()
        change = reading.visible_changes(teams).where(Change.uid == change_uid).get()
        return jsonify(reading.change_data(change, teams, detail=True))


@changes_bp.get("/changes/<uuid:change_uid>/events")
def events(change_uid):
    filters = query_input(ChangePageQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        change = Change.get(Change.uid == change_uid, Change.owner_team.in_(teams))
        order = [ChangeEvent.occurred_at.desc(), ChangeEvent.external_event_id.desc()]
        if change.ordering_mode == "sequence":
            order = [ChangeEvent.source_sequence.desc()]
        query = (
            ChangeEvent.select().where(ChangeEvent.change == change.id).order_by(*order)
        )
        return jsonify(reading.page_result(query, filters, reading.event_data))


@changes_bp.get("/changes/<uuid:change_uid>/services")
def services(change_uid):
    filters = query_input(ChangePageQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        change = reading.visible_changes(teams).where(Change.uid == change_uid).get()
        full = change.owner_team_id in teams

        def serialize(link):
            result = {
                "service": {
                    key: link[key] for key in ("id", "name", "slug", "team_id")
                },
                "relation_type": link["relation_type"],
            }
            if full and link["verification_state"] is not None:
                result["verification_state"] = link["verification_state"]
            return result

        result = reading.page_result(
            reading.service_rows(change, teams, full=full), filters, serialize
        )
        if full:
            result["references"] = reading.page_result(
                reading.reference_query(change, teams), filters, reading.reference_data
            )
        return jsonify(result)


@changes_bp.get("/changes/<uuid:change_uid>/correlations")
def correlations(change_uid):
    filters = query_input(ChangePageQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        change = reviewing.visible_change(change_uid, teams)
        return jsonify(
            reading.page_result(
                reviewing.correlation_query(change, teams),
                filters,
                lambda row: reviewing.review_data(row, teams),
            )
        )


@changes_bp.get("/alert-groups/<int:alert_group_id>/episodes")
def alert_episodes(alert_group_id):
    """List tracked episodes without reconstructing legacy alert history."""
    filters = query_input(ChangePageQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        AlertGroup.get(
            AlertGroup.id == alert_group_id,
            reviewing.visible_teams(AlertGroup.team, teams),
        )
        query = (
            reviewing.episode_query(teams)
            .where(AlertGroupEpisode.alert_group == alert_group_id)
            .order_by(AlertGroupEpisode.ordinal.desc())
        )
        return jsonify(reading.page_result(query, filters, reviewing.episode_data))


@changes_bp.get("/alert-groups/<int:alert_group_id>/related-changes")
def alert_related_changes(alert_group_id):
    """Return visible Changes and review actions for one existing episode."""
    filters = query_input(AlertRelatedChangesQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        group = AlertGroup.get(
            AlertGroup.id == alert_group_id,
            reviewing.visible_teams(AlertGroup.team, teams),
        )
        episodes = reviewing.episode_query(teams).where(
            AlertGroupEpisode.alert_group == group.id
        )
        if filters.episode_id is not None:
            episode = episodes.where(AlertGroupEpisode.id == filters.episode_id).get()
        else:
            episode = episodes.order_by(AlertGroupEpisode.ordinal.desc()).first()
        query = (
            ChangeAlertGroupCorrelation.select()
            .where(
                ChangeAlertGroupCorrelation.episode
                == (episode.id if episode else None),
                ChangeAlertGroupCorrelation.change.in_(
                    reading.visible_changes(teams).select(Change.id)
                ),
            )
            .order_by(
                ChangeAlertGroupCorrelation.score.desc(), ChangeAlertGroupCorrelation.id
            )
        )
        result = reading.page_result(
            query,
            filters,
            lambda row: {
                **reviewing.review_data(row, teams),
                "change": reading.change_data(row.change, teams),
            },
        )
        result.update(
            episode=reviewing.episode_data(episode) if episode else None,
            eligibility=episode_eligibility(episode) if episode else "no_episode",
            can_review=reviewing.can_respond(group, teams),
        )
        return jsonify(result)


@changes_bp.get("/changes/<uuid:change_uid>/correlation-targets")
def correlation_targets(change_uid):
    """Offer existing episodes by title; legacy groups never gain synthetic ones."""
    filters = query_input(ReviewTargetQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        reviewing.visible_change(change_uid, teams)
        query = reviewing.episode_query(teams)
        if filters.search:
            query = query.where(AlertGroup.title.contains(filters.search))
        return jsonify(
            reading.page_result(
                query.order_by(AlertGroupEpisode.id.desc()),
                filters,
                lambda episode: {
                    **reviewing.episode_data(episode),
                    "can_review": reviewing.can_respond(episode.alert_group, teams),
                },
            )
        )


@changes_bp.post("/changes/<uuid:change_uid>/correlations")
def create_correlation(change_uid):
    payload, error = validate_body(CorrelationCreate)
    if error:
        return error
    return jsonify(reviewing.create_correlation(change_uid, payload)), 201


@changes_bp.post("/changes/<uuid:change_uid>/correlations/<int:correlation_id>/review")
def review_correlation(change_uid, correlation_id):
    payload, error = validate_body(CorrelationReview)
    if error:
        return error
    return jsonify(reviewing.review_correlation(change_uid, correlation_id, payload))


@changes_bp.get("/changes/<uuid:change_uid>/incidents")
@changes_bp.get("/incidents/<int:incident_id>/changes")
def incident_changes(change_uid=None, incident_id=None):
    filters = query_input(IncidentChangeQuery)
    with reading.read_snapshot():
        teams = reading.reader_teams()
        change = reviewing.visible_change(change_uid, teams) if change_uid else None
        if incident_id is not None:
            incident_links.incident_query(teams).where(Incident.id == incident_id).get()
        query = incident_links.link_query(
            teams,
            incident_id=incident_id,
            change_id=change.id if change else None,
            include_removed=filters.include_removed,
        )
        return jsonify(
            reading.page_result(
                query,
                filters,
                lambda link: incident_links.link_data(link, teams),
            )
        )


@changes_bp.post("/incidents/<int:incident_id>/changes")
def add_incident_change(incident_id):
    payload, error = validate_body(IncidentChangeCreate)
    if error:
        return error
    result, status = incident_links.add_link(incident_id, payload)
    return jsonify(result), status


@changes_bp.route(
    "/incidents/<int:incident_id>/changes/<int:link_id>", methods=["PATCH", "DELETE"]
)
def mutate_incident_change(incident_id, link_id):
    remove = request.method == "DELETE"
    payload, error = validate_body(
        IncidentChangeRemove if remove else IncidentChangeUpdate
    )
    if error:
        return error
    return jsonify(
        incident_links.update_link(incident_id, link_id, payload, remove=remove)
    )
