"""Authenticated human Change reads with consistent snapshot visibility."""

from flask import Blueprint, jsonify, request
from peewee import DoesNotExist
from pydantic import ValidationError

from app.api.schemas.changes import ChangePageQuery, ChangeQuery, InvalidChangeQuery
from app.modules.db.models import Change, ChangeEvent
from app.services.change_intelligence import reading
from app.services.validation import make_error_response

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
    return make_error_response("not_found", "Change or Service not found", 404)


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
                "service": reading.service_data(link.service),
                "relation_type": link.relation_type,
            }
            if full:
                result["verification_state"] = link.verification_state
            return result

        result = reading.page_result(
            reading.service_links(change, teams, full=full), filters, serialize
        )
        if full:
            result["references"] = reading.page_result(
                reading.reference_query(change, teams), filters, reading.reference_data
            )
        return jsonify(result)
