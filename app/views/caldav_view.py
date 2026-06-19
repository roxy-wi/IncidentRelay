from defusedxml import ElementTree
from flask import Blueprint, Response, g, request

from app.services.caldav.auth import require_caldav_auth
from app.services.caldav.service import (
    find_event_by_uid,
    get_user_team_or_none,
    list_team_caldav_events,
    list_user_calendar_teams,
)
from app.services.caldav.xml import (
    APPLE_NS,
    DAV_NS,
    add_response,
    calendar_data,
    calendar_home_set,
    calendar_resource_type,
    collection_resource_type,
    current_user_principal,
    current_user_privilege_set,
    multistatus,
    principal_url,
    supported_calendar_component_set,
    text_prop,
    xml_response,
)
from app.services.caldav.ics import (
    build_event_ics,
    event_etag,
    event_href,
    event_uid,
)

caldav_bp = Blueprint("caldav", __name__, url_prefix="/caldav")


@caldav_bp.route("", methods=["OPTIONS"])
@caldav_bp.route("/", methods=["OPTIONS"])
@caldav_bp.route("/principals/<int:user_id>", methods=["OPTIONS"])
@caldav_bp.route("/principals/<int:user_id>/", methods=["OPTIONS"])
@caldav_bp.route("/calendars", methods=["OPTIONS"])
@caldav_bp.route("/calendars/", methods=["OPTIONS"])
@caldav_bp.route("/calendars/teams/<int:team_id>", methods=["OPTIONS"])
@caldav_bp.route("/calendars/teams/<int:team_id>/", methods=["OPTIONS"])
@caldav_bp.route("/calendars/teams/<int:team_id>/<uid>.ics", methods=["OPTIONS"])
def options(**kwargs):
    response = Response("", status=204)
    response.headers["DAV"] = "1, 2, calendar-access"
    response.headers["Allow"] = "OPTIONS, PROPFIND, REPORT, GET, HEAD, PROPPATCH"
    return response


@caldav_bp.route("", methods=["PROPFIND"])
@caldav_bp.route("/", methods=["PROPFIND"])
@require_caldav_auth
def propfind_root():
    user = g.caldav_user

    principal_href = f"/caldav/principals/{user.id}/"
    calendar_home_href = "/caldav/calendars/"

    root = multistatus()

    add_response(root, "/caldav/", [
        collection_resource_type(),
        text_prop(DAV_NS, "displayname", "IncidentRelay CalDAV"),
        current_user_principal(principal_href),
        principal_url(principal_href),
        calendar_home_set(calendar_home_href),
        current_user_privilege_set(read_only=True),
    ])

    return xml_response(root)


@caldav_bp.route("/principals/<int:user_id>", methods=["PROPFIND"])
@caldav_bp.route("/principals/<int:user_id>/", methods=["PROPFIND"])
@require_caldav_auth
def propfind_principal(user_id):
    user = g.caldav_user

    if user.id != user_id:
        return Response("Forbidden\n", status=403)

    principal_href = f"/caldav/principals/{user.id}/"
    calendar_home_href = "/caldav/calendars/"

    root = multistatus()

    add_response(root, principal_href, [
        collection_resource_type(),
        text_prop(DAV_NS, "displayname", user.username or user.email or f"user-{user.id}"),
        principal_url(principal_href),
        calendar_home_set(calendar_home_href),
        current_user_privilege_set(read_only=True),
    ])

    return xml_response(root)


@caldav_bp.route("/calendars", methods=["PROPFIND"])
@caldav_bp.route("/calendars/", methods=["PROPFIND"])
@require_caldav_auth
def propfind_calendar_home():
    user = g.caldav_user
    root = multistatus()

    add_response(root, "/caldav/calendars/", [
        collection_resource_type(),
        text_prop(DAV_NS, "displayname", "IncidentRelay calendars"),
        current_user_privilege_set(read_only=True),
    ])

    for team in list_user_calendar_teams(user):
        add_response(root, f"/caldav/calendars/teams/{team.id}/", [
            calendar_resource_type(),
            text_prop(DAV_NS, "displayname", f"{team.name} on-call"),
            text_prop(APPLE_NS, "calendar-color", "#3b82f6"),
            supported_calendar_component_set(),
            current_user_privilege_set(read_only=True),
        ])

    return xml_response(root)


@caldav_bp.route("/calendars/teams/<int:team_id>", methods=["PROPFIND"])
@caldav_bp.route("/calendars/teams/<int:team_id>/", methods=["PROPFIND"])
@require_caldav_auth
def propfind_team_calendar(team_id):
    user = g.caldav_user
    team = get_user_team_or_none(user, team_id)

    if not team:
        return Response("Calendar not found\n", status=404)

    depth = request.headers.get("Depth", "0")
    root = multistatus()

    add_response(root, f"/caldav/calendars/teams/{team.id}/", [
        calendar_resource_type(),
        text_prop(DAV_NS, "displayname", f"{team.name} on-call"),
        text_prop(APPLE_NS, "calendar-color", "#3b82f6"),
        supported_calendar_component_set(),
        current_user_privilege_set(read_only=True),
    ])

    if depth == "1":
        for event in list_team_caldav_events(team):
            add_response(root, event_href(team.id, event), [
                text_prop(DAV_NS, "getcontenttype", "text/calendar; charset=utf-8"),
                text_prop(DAV_NS, "getetag", event_etag(event)),
                current_user_privilege_set(read_only=True),
            ])

    return xml_response(root)


@caldav_bp.route("/calendars/teams/<int:team_id>", methods=["REPORT"])
@caldav_bp.route("/calendars/teams/<int:team_id>/", methods=["REPORT"])
@require_caldav_auth
def report_team_calendar(team_id):
    user = g.caldav_user
    team = get_user_team_or_none(user, team_id)

    if not team:
        return Response("Calendar not found\n", status=404)

    report_kind, hrefs = get_report_kind()

    if report_kind == "unknown":
        return Response("Unsupported REPORT\n", status=400)

    root = multistatus()

    for event in list_team_caldav_events(team):
        if not event_matches_requested_hrefs(team.id, event, hrefs):
            continue

        add_calendar_event_response(root, team.id, event)

    return xml_response(root)


@caldav_bp.route("/calendars/teams/<int:team_id>/<uid>.ics", methods=["GET", "HEAD"])
@require_caldav_auth
def get_calendar_object(team_id, uid):
    user = g.caldav_user
    team = get_user_team_or_none(user, team_id)

    if not team:
        return Response("Calendar not found\n", status=404)

    event = find_event_by_uid(team, uid)

    if not event:
        return Response("Event not found\n", status=404)

    body = build_event_ics(event)

    response = Response(
        "" if request.method == "HEAD" else body,
        mimetype="text/calendar; charset=utf-8",
    )
    response.headers["ETag"] = event_etag(event)
    response.headers["Content-Disposition"] = (
        f'inline; filename="{uid}.ics"'
    )

    return response


def proppatch_multistatus_response(href):
    """Return successful WebDAV PROPPATCH response.

    Apple Calendar sends PROPPATCH to store client-side calendar properties
    like color, display name or order. IncidentRelay is read-only, but these
    client-side updates are harmless, so we accept them as no-op.
    """
    root = multistatus()
    add_response(root, href, [])
    return xml_response(root, status=207)


@caldav_bp.route("", methods=["PROPPATCH"])
@caldav_bp.route("/", methods=["PROPPATCH"])
@require_caldav_auth
def proppatch_root():
    return proppatch_multistatus_response("/caldav/")


@caldav_bp.route("/calendars", methods=["PROPPATCH"])
@caldav_bp.route("/calendars/", methods=["PROPPATCH"])
@require_caldav_auth
def proppatch_calendar_home():
    return proppatch_multistatus_response("/caldav/calendars/")


@caldav_bp.route("/principals/<int:user_id>", methods=["PROPPATCH"])
@caldav_bp.route("/principals/<int:user_id>/", methods=["PROPPATCH"])
@require_caldav_auth
def proppatch_principal(user_id):
    user = g.caldav_user

    if user.id != user_id:
        return Response("Forbidden\n", status=403)

    return proppatch_multistatus_response(f"/caldav/principals/{user.id}/")


@caldav_bp.route("/calendars/teams/<int:team_id>", methods=["PROPPATCH"])
@caldav_bp.route("/calendars/teams/<int:team_id>/", methods=["PROPPATCH"])
@require_caldav_auth
def proppatch_team_calendar(team_id):
    user = g.caldav_user
    team = get_user_team_or_none(user, team_id)

    if not team:
        return Response("Calendar not found\n", status=404)

    return proppatch_multistatus_response(
        f"/caldav/calendars/teams/{team.id}/"
    )


@caldav_bp.route("", methods=["PUT", "DELETE", "MKCALENDAR"])
@caldav_bp.route("/", methods=["PUT", "DELETE", "MKCALENDAR"])
@caldav_bp.route("/principals/<path:any_path>", methods=["PUT", "DELETE", "MKCALENDAR"])
@caldav_bp.route("/calendars/<path:any_path>", methods=["PUT", "DELETE", "MKCALENDAR"])
def readonly_methods(**kwargs):
    return Response("IncidentRelay CalDAV is read-only\n", status=403)


def get_report_kind():
    """Return CalDAV REPORT kind from XML request body."""
    raw_body = request.get_data(cache=True) or b""

    if not raw_body.strip():
        return "calendar-query", []

    try:
        root = ElementTree.fromstring(raw_body)
    except ElementTree.ParseError:
        return "calendar-query", []

    tag = root.tag.lower()

    hrefs = []
    for element in root.iter():
        if element.tag.endswith("href") and element.text:
            hrefs.append(element.text.strip())

    if tag.endswith("calendar-multiget"):
        return "calendar-multiget", hrefs

    if tag.endswith("calendar-query"):
        return "calendar-query", hrefs

    return "unknown", hrefs


def event_matches_requested_hrefs(team_id, event, hrefs):
    if not hrefs:
        return True

    expected_href = event_href(team_id, event)
    expected_uid_href = f"/caldav/calendars/teams/{team_id}/{event_uid(event)}.ics"

    normalized_hrefs = {
        href.split("://", 1)[-1].split("/", 1)[-1]
        if "://" in href else href
        for href in hrefs
    }

    normalized_expected = {
        expected_href,
        expected_href.lstrip("/"),
        expected_uid_href,
        expected_uid_href.lstrip("/"),
    }

    return bool(normalized_hrefs & normalized_expected)


def add_calendar_event_response(root, team_id, event):
    add_response(root, event_href(team_id, event), [
        text_prop(DAV_NS, "getcontenttype", "text/calendar; charset=utf-8"),
        text_prop(DAV_NS, "getetag", event_etag(event)),
        calendar_data(build_event_ics(event)),
    ])
