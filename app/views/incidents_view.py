from flask import Blueprint, jsonify, request
from peewee import IntegrityError
from urllib.parse import urlsplit

from app.api.schemas.incidents import (
    IncidentAssignmentSchema,
    IncidentParticipantCreateSchema,
    IncidentResponderCreateSchema,
    IncidentResponderUpdateSchema,
    IncidentStakeholderCreateSchema,
    IncidentCommentCreateSchema,
    IncidentAffectedServiceSchema,
    IncidentCreateSchema,
    IncidentLinkSchema,
    IncidentTransitionSchema,
    IncidentUpdateSchema,
)
from app.modules.db import incident_core_repo, incidents_repo
from app.services.audit import current_api_token_id
from app.services.incidents.core import _audit
from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db.models import (AlertGroup, AlertComment, AlertEvent, IncidentComment, IncidentService,
                                  IncidentResponder, IncidentStakeholder, Service, ServiceRunbook, ServiceLink, ServiceDependency, User)
from app.services.incidents.core import (
    IncidentConflictError,
    IncidentValidationError,
    assign_incident,
    create_incident,
    link_alert_group,
    transition_incident,
    unlink_alert_group,
    update_incident,
)
from app.services.rbac import (
    can_access_team_or_group_resource,
    can_respond_team,
    get_allowed_team_ids,
    is_admin_user,
    require_team_read,
    require_team_respond,
)
from app.services.serializers.alerts import serialize_incident_priority, serialize_incident_responder
from app.services.serializers.incidents import (
    serialize_incident,
    serialize_incident_event,
    serialize_incident_link,
)
from app.services.validation import make_error_response, safe_exception_response, validate_body


from app.services.incidents.responders import (
    create_incident_responder as request_incident_responder,
    set_incident_responder_status,
)

incidents_bp = Blueprint("incidents_api", __name__)


def _request_user():
    return getattr(request, "current_user", None)


def _request_user_id():
    return getattr(_request_user(), "id", None)


def _can_create_incident(user, team_id):
    if not user:
        return False
    if is_admin_user(user):
        return True
    return can_respond_team(user, team_id) or can_access_team_or_group_resource(
        user,
        team_id,
        write_required=True,
    )


def _get_incident_or_error(incident_id, *, respond=False):
    incident = incident_core_repo.get_incident(incident_id)
    if not incident:
        return None, make_error_response("not_found", "Incident not found", 404)
    if incident.team_id:
        error = require_team_respond(incident.team_id) if respond else require_team_read(incident.team_id)
        if error:
            return None, error
    elif not is_admin_user(_request_user()):
        return None, make_error_response("forbidden", "Incident is outside your team scope", 403)
    return incident, None


def _service_error(exc):
    if isinstance(exc, IncidentConflictError):
        return make_error_response("conflict", str(exc), 409)
    return make_error_response("validation_error", str(exc), 400)


@incidents_bp.route("", methods=["GET"])
def list_incidents():
    team_id = request.args.get("team_id", type=int)
    statuses = [value for value in request.args.getlist("status") if value]
    if not statuses and request.args.get("status"):
        statuses = [request.args.get("status")]

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        team_ids = [team_id]
    else:
        team_ids = get_allowed_team_ids()

    incidents = incident_core_repo.list_incidents(team_ids=team_ids, statuses=statuses)
    search = (request.args.get("search") or "").strip().lower()
    if search:
        incidents = [item for item in incidents if search in (item.title or "").lower()]

    page = max(request.args.get("page", 1, type=int), 1)
    page_size = min(max(request.args.get("page_size", 25, type=int), 1), 100)
    total = len(incidents)
    start = (page - 1) * page_size
    items = incidents[start:start + page_size]

    return jsonify({
        "items": [serialize_incident(item, current_user=_request_user()) for item in items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size if total else 0,
        },
    })


@incidents_bp.route("", methods=["POST"])
def create_incident_view():
    payload, error = validate_body(IncidentCreateSchema)
    if error:
        return error
    if not _can_create_incident(_request_user(), payload.team_id):
        return make_error_response("forbidden", "Incident create permission is required for this team", 403)
    try:
        incident = create_incident(
            team_id=payload.team_id,
            service_id=payload.service_id,
            title=payload.title,
            description=payload.description,
            priority_slug=payload.priority,
            assignee_id=payload.assignee_id,
            user_id=_request_user_id(),
            api_token_id=current_api_token_id(),
            source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True)), 201


@incidents_bp.route("/priorities", methods=["GET"])
def list_incident_priorities():
    include_disabled = request.args.get("include_disabled") == "1"
    return jsonify([
        serialize_incident_priority(priority)
        for priority in incidents_repo.list_priorities(include_disabled=include_disabled)
    ])


def _visible_alert_group_links(incident):
    """Apply technical-team visibility on every Incident-to-AlertGroup read.

    Owning an Incident never grants access to its linked technical signals.
    Filtering here also protects the nested link list in the Incident detail.
    """
    visible = []
    for link in incident_core_repo.list_active_links(incident.id):
        group = link.alert_group
        if group.team_id:
            if require_team_read(group.team_id):
                continue
        elif not is_admin_user(_request_user()):
            continue
        visible.append(link)
    return visible


@incidents_bp.route("/<int:incident_id>", methods=["GET"])
def get_incident(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    payload = serialize_incident(incident, current_user=_request_user(), include_details=True)
    payload["alert_groups"] = [serialize_incident_link(link) for link in _visible_alert_group_links(incident)]
    payload["events"] = [serialize_incident_event(event) for event in incident_core_repo.list_events(incident.id)]
    return jsonify(payload)


@incidents_bp.route("/<int:incident_id>", methods=["PATCH"])
def update_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentUpdateSchema)
    if error:
        return error
    try:
        incident = update_incident(
            incident.id,
            expected_version=payload.row_version,
            user_id=_request_user_id(),
            api_token_id=current_api_token_id(),
            source="api",
            title=payload.title,
            description=payload.description,
            service_id=payload.service_id,
            priority_slug=payload.priority,
            root_cause=payload.root_cause,
            resolution_summary=payload.resolution_summary,
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/status", methods=["POST"])
def transition_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentTransitionSchema)
    if error:
        return error
    try:
        incident = transition_incident(
            incident.id,
            payload.status,
            expected_version=payload.row_version,
            user_id=_request_user_id(),
            api_token_id=current_api_token_id(),
            source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/close", methods=["POST"])
def close_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    row_version = payload.get("row_version")
    if not isinstance(row_version, int) or row_version < 1:
        return make_error_response("validation_error", "row_version is required", 400)
    try:
        incident = transition_incident(
            incident.id, "closed", expected_version=row_version,
            user_id=_request_user_id(), api_token_id=current_api_token_id(),
            source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/reopen", methods=["POST"])
def reopen_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    row_version = payload.get("row_version")
    if not isinstance(row_version, int) or row_version < 1:
        return make_error_response("validation_error", "row_version is required", 400)
    try:
        incident = transition_incident(
            incident.id, "investigating", expected_version=row_version,
            user_id=_request_user_id(), api_token_id=current_api_token_id(),
            source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/assignee", methods=["PUT"])
def assign_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentAssignmentSchema)
    if error:
        return error
    try:
        incident = assign_incident(
            incident.id,
            assignee_id=payload.assignee_id,
            expected_version=payload.row_version,
            user_id=_request_user_id(),
            api_token_id=current_api_token_id(),
            source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/assignee/me", methods=["PUT"])
def assign_incident_to_me_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    row_version = payload.get("row_version")
    if not isinstance(row_version, int) or row_version < 1:
        return make_error_response("validation_error", "row_version is required", 400)
    if not _request_user_id():
        return make_error_response("forbidden", "Authenticated user is required", 403)
    try:
        incident = assign_incident(
            incident.id,
            assignee_id=_request_user_id(),
            expected_version=row_version,
            user_id=_request_user_id(),
            api_token_id=current_api_token_id(),
            source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/alert-groups", methods=["GET"])
def list_incident_alert_groups(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    return jsonify([serialize_incident_link(link) for link in _visible_alert_group_links(incident)])


@incidents_bp.route("/<int:incident_id>/alert-groups", methods=["POST"])
def link_incident_alert_group(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentLinkSchema)
    if error:
        return error

    alert_group = AlertGroup.get_or_none(AlertGroup.id == payload.alert_group_id)
    if not alert_group:
        return make_error_response("not_found", "Alert group not found", 404)
    if alert_group.team_id:
        error = require_team_respond(alert_group.team_id)
        if error:
            return error
    elif not is_admin_user(_request_user()):
        return make_error_response("forbidden", "Alert group has no team scope", 403)

    try:
        link = link_alert_group(
            incident.id,
            payload.alert_group_id,
            relation_type=payload.relation_type,
            user_id=_request_user_id(),
            api_token_id=current_api_token_id(),
            source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident_link(link)), 201


@incidents_bp.route("/<int:incident_id>/alert-groups/<int:group_id>", methods=["DELETE"])
def unlink_incident_alert_group(incident_id, group_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    # Do not allow Incident operators to mutate an unrelated team's signal.
    link = next((item for item in incident_core_repo.list_active_links(incident.id)
                 if item.alert_group_id == group_id), None)
    if link is None:
        return make_error_response("not_found", "Active Incident/AlertGroup link not found", 404)
    group = link.alert_group
    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error
    elif not is_admin_user(_request_user()):
        return make_error_response("forbidden", "Alert group has no team scope", 403)
    try:
        link = unlink_alert_group(
            incident.id, group_id, user_id=_request_user_id(),
            api_token_id=current_api_token_id(), source="api",
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    if not link:
        return make_error_response("not_found", "Active Incident/AlertGroup link not found", 404)
    return jsonify({"unlinked": True, "link": serialize_incident_link(link)})


@incidents_bp.route("/<int:incident_id>/events", methods=["GET"])
def list_incident_events(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    return jsonify([serialize_incident_event(event) for event in incident_core_repo.list_events(incident.id)])


# Collaboration data belongs to the operational Incident, never to AlertGroup.
def _serialize_comment(comment):
    return {
        "id": comment.id,
        "incident_id": comment.incident_id,
        "author_id": comment.author_id,
        "author": ({"id": comment.author.id, "display_name": comment.author.display_name,
                    "username": comment.author.username} if comment.author_id else None),
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
    }


def _safe_service_url(value):
    """Expose only browser-safe web links stored in service metadata."""
    if not value or not isinstance(value, str):
        return None
    candidate = value.strip()
    # Reject embedded whitespace/control characters and credential-bearing URLs.
    # URL parsers normalize some control characters instead of rejecting them.
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127
           for character in candidate):
        return None
    try:
        parsed = urlsplit(candidate)
        if (parsed.scheme.lower() not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
        # Accessing .port validates malformed port values.
        _ = parsed.port
    except ValueError:
        return None
    return candidate


def _visible_service_dependencies(service):
    """Never expose dependency names belonging to inaccessible teams."""
    result = []
    links = (ServiceDependency.select(ServiceDependency, Service)
             .join(Service, on=(ServiceDependency.depends_on_service == Service.id))
             .where(ServiceDependency.service == service.id,
                    ServiceDependency.enabled == True,  # noqa: E712
                    ServiceDependency.deleted == False,  # noqa: E712
                    Service.enabled == True,  # noqa: E712
                    Service.deleted == False))  # noqa: E712
    for dependency in links:
        target = dependency.depends_on_service
        if not target.team_id or require_team_read(target.team_id):
            continue
        result.append({"service_id": target.id, "name": target.name,
                       "criticality": dependency.criticality,
                       "dependency_type": dependency.dependency_type})
    return result


def _serialize_service(link):
    service = link.service
    runbooks = (ServiceRunbook.select()
                .where(ServiceRunbook.service == service.id,
                       ServiceRunbook.enabled == True,  # noqa: E712
                       ServiceRunbook.deleted == False)  # noqa: E712
                .order_by(ServiceRunbook.priority, ServiceRunbook.id))
    external_links = (ServiceLink.select()
                      .where(ServiceLink.service == service.id,
                             ServiceLink.enabled == True,  # noqa: E712
                             ServiceLink.deleted == False)  # noqa: E712
                      .order_by(ServiceLink.priority, ServiceLink.id))
    return {
        "id": link.id, "incident_id": link.incident_id, "service_id": service.id,
        "service_name": service.name, "service_slug": service.slug,
        "status": service.status, "criticality": service.criticality,
        "tier": service.tier, "environment": service.environment,
        "team_id": service.team_id,
        "runbooks": [{"title": item.title, "url": url}
                     for item in runbooks if (url := _safe_service_url(item.url))],
        "links": [{"label": item.label, "type": item.link_type, "url": url}
                  for item in external_links if (url := _safe_service_url(item.url))],
        "dependencies": _visible_service_dependencies(service),
        "added_at": link.added_at.isoformat() if link.added_at else None,
    }


@incidents_bp.route("/<int:incident_id>/comments", methods=["GET"])
def list_incident_comments(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    comments = (IncidentComment.select().where(IncidentComment.incident == incident.id)
                .order_by(IncidentComment.created_at, IncidentComment.id))
    return jsonify([_serialize_comment(comment) for comment in comments])


@incidents_bp.route("/<int:incident_id>/comments", methods=["POST"])
def add_incident_comment(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    if _request_user_id() is None:
        return make_error_response("forbidden", "Authenticated user is required", 403)
    payload, error = validate_body(IncidentCommentCreateSchema)
    if error:
        return error
    with db.atomic():
        comment = IncidentComment.create(incident=incident, author=_request_user_id(), body=payload.body)
        incident_core_repo.create_event(incident.id, "incident_comment_added", user_id=_request_user_id(),
                                        data={"comment_id": comment.id})
        _audit("incident.comment_add", incident, user_id=_request_user_id(),
               api_token_id=current_api_token_id(), source="api", data={"comment_id": comment.id})
    from app.services.incidents.stakeholders import notify_stakeholders
    notify_stakeholders(incident, "comment_added", skip_user_id=_request_user_id())
    return jsonify(_serialize_comment(comment)), 201


@incidents_bp.route("/<int:incident_id>/affected-services", methods=["GET"])
def list_incident_affected_services(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    # Each service has an independent team scope. Never leak cross-team relations.
    links = IncidentService.select().where(IncidentService.incident == incident.id).order_by(IncidentService.id)
    visible = []
    for link in links:
        if link.service.team_id and require_team_read(link.service.team_id):
            continue
        visible.append(_serialize_service(link))
    return jsonify(visible)


@incidents_bp.route("/<int:incident_id>/affected-services", methods=["POST"])
def add_incident_affected_service(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentAffectedServiceSchema)
    if error:
        return error
    service = Service.get_or_none(Service.id == payload.service_id,
                                  Service.enabled == True, Service.deleted == False)  # noqa: E712
    if service is None:
        return make_error_response("not_found", "Service not found", 404)
    if service.team_id:
        error = require_team_respond(service.team_id)
        if error:
            return error
    elif not is_admin_user(_request_user()):
        return make_error_response("forbidden", "Service has no team scope", 403)
    with db.atomic():
        existing = IncidentService.get_or_none(IncidentService.incident == incident.id,
                                               IncidentService.service == service.id)
        if existing:
            return jsonify(_serialize_service(existing)), 200
        link = IncidentService.create(incident=incident, service=service, added_at=utc_now())
        incident_core_repo.create_event(incident.id, "incident_service_added", user_id=_request_user_id(),
                                        data={"service_id": service.id})
        _audit("incident.service_add", incident, user_id=_request_user_id(),
               api_token_id=current_api_token_id(), source="api", data={"service_id": service.id})
    return jsonify(_serialize_service(link)), 201


@incidents_bp.route("/<int:incident_id>/affected-services/<int:service_id>", methods=["DELETE"])
def remove_incident_affected_service(incident_id, service_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    link = IncidentService.get_or_none(IncidentService.incident == incident.id,
                                       IncidentService.service == service_id)
    if link is None:
        return make_error_response("not_found", "Affected service not found", 404)
    if link.service.team_id:
        error = require_team_respond(link.service.team_id)
        if error:
            return error
    elif not is_admin_user(_request_user()):
        return make_error_response("forbidden", "Service has no team scope", 403)
    with db.atomic():
        link.delete_instance()
        incident_core_repo.create_event(incident.id, "incident_service_removed", user_id=_request_user_id(),
                                        data={"service_id": service_id})
        _audit("incident.service_remove", incident, user_id=_request_user_id(),
               api_token_id=current_api_token_id(), source="api", data={"service_id": service_id})
    return jsonify({"removed": True})


# 2.5 canonical, concrete-user Incident participants. On-call schedule changes
# cannot silently reassign these persisted operational roles.
def _participant_json(row):
    user = row.target_user if row.target_user_id else None
    return {"id": row.id, "incident_id": row.incident_id, "user_id": row.target_user_id,
            "user": ({"id": user.id, "display_name": user.display_name,
                      "username": user.username, "email": user.email} if user else None),
            "role": row.role, "assigned_by_id": row.requested_by_id,
            "created_at": row.created_at.isoformat() if row.created_at else None}


@incidents_bp.route("/<int:incident_id>/participants", methods=["GET"])
def list_incident_participants(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    rows = (IncidentResponder.select()
            .where(IncidentResponder.incident == incident.id,
                   IncidentResponder.status == "accepted")
            .order_by(IncidentResponder.id))
    return jsonify([_participant_json(row) for row in rows])


@incidents_bp.route("/<int:incident_id>/participants", methods=["POST"])
def add_incident_participant(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    actor_id = _request_user_id()
    if actor_id is None:
        return make_error_response("forbidden", "Authenticated user required", 403)
    payload, error = validate_body(IncidentParticipantCreateSchema)
    if error:
        return error
    user = User.get_or_none(User.id == payload.user_id, User.active == True, User.deleted == False)  # noqa: E712
    if user is None:
        return make_error_response("not_found", "User not found", 404)
    # Assignment requires membership in the Incident's owning group, not
    # membership in the actor's team. An Incident can span multiple teams.
    if incident.team_id:
        from app.modules.db.models import UserGroup
        in_group = UserGroup.select().where(
            UserGroup.user == user.id,
            UserGroup.group == incident.team.group_id,
            UserGroup.active == True,  # noqa: E712
        ).exists()
        if not in_group:
            return make_error_response("validation_error", "User is outside Incident group", 400)
    with db.atomic():
        if payload.role == "commander" and IncidentResponder.select().where(
            IncidentResponder.incident == incident.id,
            IncidentResponder.role == "commander",
            IncidentResponder.status == "accepted",
        ).exists():
            return make_error_response("conflict", "Incident already has a commander", 409)

        if IncidentResponder.select().where(
            IncidentResponder.incident == incident.id,
            IncidentResponder.target_user == user.id,
            IncidentResponder.role == payload.role,
            IncidentResponder.status == "accepted",
        ).exists():
            return make_error_response("conflict", "Participant already assigned", 409)
        try:
            row = IncidentResponder.create(incident=incident, target_user=user,
                                             target_type="user", role=payload.role,
                                             status="accepted", requested_by=actor_id,
                                             accepted_by=actor_id, responded_at=utc_now())
        except IntegrityError:
            return make_error_response("conflict", "Participant already assigned", 409)
        incident_core_repo.create_event(incident.id, "participant_added", user_id=actor_id,
                                        data={"participant_id": row.id, "user_id": user.id, "role": payload.role})
        _audit("incident.participant_add", incident, user_id=actor_id,
               api_token_id=current_api_token_id(), source="api",
               data={"participant_id": row.id, "user_id": user.id, "role": payload.role})
    return jsonify(_participant_json(row)), 201


@incidents_bp.route("/<int:incident_id>/participants/<int:participant_id>", methods=["DELETE"])
def remove_incident_participant(incident_id, participant_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    actor_id = _request_user_id()
    if actor_id is None:
        return make_error_response("forbidden", "Authenticated user required", 403)
    with db.atomic():
        row = IncidentResponder.get_or_none(IncidentResponder.id == participant_id,
                                              IncidentResponder.incident == incident.id,
                                              IncidentResponder.status == "accepted")
        if row is None:
            return make_error_response("not_found", "Participant not found", 404)
        detail = {"participant_id": row.id, "user_id": row.target_user_id, "role": row.role}
        row.status = "resolved"
        row.updated_at = utc_now()
        row.save(only=[IncidentResponder.status, IncidentResponder.updated_at])
        incident_core_repo.create_event(incident.id, "participant_removed", user_id=actor_id, data=detail)
        _audit("incident.participant_remove", incident, user_id=actor_id,
               api_token_id=current_api_token_id(), source="api", data=detail)
    return "", 204


# Operational stakeholders are independent from legacy AlertGroup subscriptions.
def _operational_stakeholder_json(row):
    return {
        "id": row.id,
        "incident_id": row.incident_id,
        "user_id": row.user_id,
        "email": row.email,
        "display_name": row.display_name,
        "user": ({"id": row.user.id, "display_name": row.user.display_name,
                  "username": row.user.username, "email": row.user.email} if row.user_id else None),
        "role": row.role,
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@incidents_bp.route("/<int:incident_id>/stakeholders", methods=["GET"])
def list_operational_stakeholders(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    rows = (IncidentStakeholder.select()
            .where(IncidentStakeholder.incident == incident.id,
                   IncidentStakeholder.active == True)  # noqa: E712
            .order_by(IncidentStakeholder.id))
    return jsonify([_operational_stakeholder_json(row) for row in rows])


@incidents_bp.route("/<int:incident_id>/stakeholders", methods=["POST"])
def add_operational_stakeholder(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    actor = _request_user_id()
    if actor is None:
        return make_error_response("forbidden", "Authenticated user required", 403)
    payload, error = validate_body(IncidentStakeholderCreateSchema)
    if error:
        return error
    if payload.user_id:
        user = User.get_or_none(User.id == payload.user_id,
                                User.active == True, User.deleted == False)  # noqa: E712
        if user is None:
            return make_error_response("not_found", "Stakeholder user not found", 404)
        if incident.team_id and incident.team.group_id:
            from app.modules.db.models import UserGroup
            if not UserGroup.select().where(
                UserGroup.user == user.id,
                UserGroup.group == incident.team.group_id,
                UserGroup.active == True,  # noqa: E712
            ).exists():
                return make_error_response("forbidden", "User outside incident group", 403)
    else:
        user = None
    with db.atomic():
        # Include inactive rows so re-subscription never duplicates a stakeholder.
        lookup = ((IncidentStakeholder.user == user.id) if user else
                  (IncidentStakeholder.email == payload.email))
        row = (IncidentStakeholder.select().where(
            IncidentStakeholder.incident == incident.id, lookup).first())
        if row is not None and row.active:
            return jsonify(_operational_stakeholder_json(row)), 200
        if row is None:
            row = IncidentStakeholder.create(
                incident=incident, user=user, email=payload.email,
                display_name=payload.display_name, role=payload.role,
                created_by=actor, source="manual")
        else:
            row.active = True
            row.role = payload.role
            row.updated_at = utc_now()
            row.save(only=[IncidentStakeholder.active,
                           IncidentStakeholder.role,
                           IncidentStakeholder.updated_at])
        detail = {"stakeholder_id": row.id, "user_id": row.user_id, "role": row.role}
        incident_core_repo.create_event(incident.id, "stakeholder_added", user_id=actor, data=detail)
        _audit("incident.stakeholder_add", incident, user_id=actor,
               api_token_id=current_api_token_id(), source="api", data=detail)
    return jsonify(_operational_stakeholder_json(row)), 201


@incidents_bp.route("/<int:incident_id>/stakeholders/<int:stakeholder_id>", methods=["DELETE"])
def remove_operational_stakeholder(incident_id, stakeholder_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    actor = _request_user_id()
    if actor is None:
        return make_error_response("forbidden", "Authenticated user required", 403)
    with db.atomic():
        row = IncidentStakeholder.get_or_none(
            IncidentStakeholder.id == stakeholder_id,
            IncidentStakeholder.incident == incident.id,
            IncidentStakeholder.active == True)  # noqa: E712
        if row is None:
            return make_error_response("not_found", "Stakeholder not found", 404)
        row.active = False
        row.updated_at = utc_now()
        row.save(only=[IncidentStakeholder.active,
                       IncidentStakeholder.updated_at])
        detail = {"stakeholder_id": row.id, "user_id": row.user_id}
        incident_core_repo.create_event(incident.id, "stakeholder_removed", user_id=actor, data=detail)
        _audit("incident.stakeholder_remove", incident, user_id=actor,
               api_token_id=current_api_token_id(), source="api", data=detail)
    return "", 204


@incidents_bp.route("/<int:incident_id>/responders", methods=["GET"])
def get_incident_responders(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    return jsonify([serialize_incident_responder(row) for row in
        incidents_repo.list_incident_responders(incident.id)])


@incidents_bp.route("/<int:incident_id>/responders", methods=["POST"])
def request_incident_responder_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentResponderCreateSchema)
    if error:
        return error
    actor = _request_user_id()
    if actor is None:
        return make_error_response("forbidden", "Authenticated user required", 403)
    try:
        row = request_incident_responder(
            incident_id=incident.id, payload=payload.model_dump(), user_id=actor)
    except (ValueError, KeyError) as exc:
        return safe_exception_response(exc, error="validation_error",
                                       message="Invalid responder request", status_code=400)
    except LookupError:
        return make_error_response("not_found", "Incident not found", 404)
    _audit("incident.responder.request", incident, user_id=actor,
           api_token_id=current_api_token_id(), source="api", data={"responder_id": row.id})
    return jsonify(serialize_incident_responder(row)), 201


@incidents_bp.route("/<int:incident_id>/responders/<int:responder_id>", methods=["PUT"])
def update_incident_responder_view(incident_id, responder_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    payload, error = validate_body(IncidentResponderUpdateSchema)
    if error:
        return error
    user = _request_user()
    if user is None:
        return make_error_response("forbidden", "Authenticated user required", 403)
    try:
        row = set_incident_responder_status(
            incident_id=incident.id, responder_id=responder_id,
            status=payload.status, response_message=payload.response_message,
            user_id=user.id, user=user)
    except PermissionError:
        return make_error_response("forbidden", "Responder action forbidden", 403)
    except LookupError:
        return make_error_response("not_found", "Responder not found", 404)
    except ValueError as exc:
        return safe_exception_response(exc, error="validation_error",
                                       message="Invalid responder transition", status_code=400)
    _audit("incident.responder.status", incident, user_id=user.id,
           api_token_id=current_api_token_id(), source="api",
           data={"responder_id": row.id, "status": row.status})
    return jsonify(serialize_incident_responder(row))

# 2.5: canonical Incident collaboration endpoints above.


# Activity is a read model, not a migration or a duplication of technical comments.
# Unlinked and unauthorized AlertGroups must never contribute technical data.
def _incident_activity_rows(incident, *, limit=200):
    entries = []
    for event in incident_core_repo.list_events(incident.id, limit=limit):
        entries.append({"source_type": "Incident", "source_id": incident.id,
                        "target_type": "Incident", "target_id": incident.id,
                        "record_type": "event", "record_id": event.id,
                        "event_type": event.event_type, "actor_id": event.user_id,
                        "message": event.message, "created_at": event.created_at.isoformat(),
                        "_sort_at": event.created_at})
    # Incident comments have their own stable IDs and must not be synthesized
    # from event.data (which contains a reference, not the comment content).
    comments = (IncidentComment.select()
                .where(IncidentComment.incident == incident.id)
                .order_by(IncidentComment.created_at.desc(), IncidentComment.id.desc())
                .limit(limit))
    for comment in comments:
        entries.append({"source_type": "Incident", "source_id": incident.id,
                        "target_type": "Incident", "target_id": incident.id,
                        "record_type": "comment", "record_id": comment.id,
                        "event_type": "comment", "actor_id": comment.author_id,
                        "message": comment.body, "created_at": comment.created_at.isoformat(),
                        "_sort_at": comment.created_at})

    visible_groups = []
    for link in incident_core_repo.list_active_links(incident.id):
        group = link.alert_group
        if group.team_id:
            if require_team_read(group.team_id):
                continue
        elif not is_admin_user(_request_user()):
            continue
        visible_groups.append(group.id)
    if visible_groups:
        events = (AlertEvent.select()
                  .where(AlertEvent.group.in_(visible_groups))
                  .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
                  .limit(limit))
        for event in events:
            entries.append({"source_type": "AlertGroup", "source_id": event.group_id,
                            "target_type": "AlertGroup", "target_id": event.group_id,
                            "record_type": "event", "record_id": event.id,
                            "event_type": event.event_type, "actor_id": event.user_id,
                            "message": event.message, "created_at": event.created_at.isoformat(),
                            "_sort_at": event.created_at})
        comments = (AlertComment.select()
                    .where(AlertComment.group.in_(visible_groups),
                           AlertComment.alert.is_null(True),
                           AlertComment.deleted == False)  # noqa: E712
                    .order_by(AlertComment.created_at.desc(), AlertComment.id.desc())
                    .limit(limit))
        for comment in comments:
            entries.append({"source_type": "AlertGroup", "source_id": comment.group_id,
                            "target_type": "AlertGroup", "target_id": comment.group_id,
                            "record_type": "comment", "record_id": comment.id,
                            "event_type": "comment", "actor_id": comment.user_id,
                            "message": comment.body, "created_at": comment.created_at.isoformat(),
                            "_sort_at": comment.created_at})

    entries.sort(key=lambda item: (item["_sort_at"], item["source_type"],
                                   item["record_type"], item["record_id"]), reverse=True)
    return [{key: value for key, value in item.items() if key != "_sort_at"}
            for item in entries[:limit]]


@incidents_bp.route("/<int:incident_id>/activity", methods=["GET"])
def list_incident_activity(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    raw_limit = request.args.get("limit", "200")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return make_error_response("validation_error", "limit must be an integer", 400)
    if not 1 <= limit <= 500:
        return make_error_response("validation_error", "limit must be between 1 and 500", 400)
    return jsonify(_incident_activity_rows(incident, limit=limit))
