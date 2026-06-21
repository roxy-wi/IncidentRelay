import base64
from datetime import datetime, timedelta
from xml.etree import ElementTree

from app.modules.db import tokens_repo
from app.modules.db.models import ApiToken
from app.services.integrations.auth import hash_token
from app.services.caldav.ics import event_href, event_uid
from app.services.caldav.service import list_team_caldav_events
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_team,
    create_user,
    unique,
)


def unfold_ics(value: str) -> str:
    return value.replace("\r\n ", "").replace("\n ", "")


def basic_auth(username, token):
    value = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {value}"}


def create_personal_token(user, scopes=None, token_value=None, expires_at=None):
    token_value = token_value or unique("caldav-token")
    token = tokens_repo.create_token(
        name=unique("token"),
        token_prefix=token_value[:12],
        token_hash=hash_token(token_value),
        scopes=scopes or ["calendar:read"],
        user=user.id,
        expires_at=expires_at,
    )

    return token_value, token


def caldav_headers(user, scopes=None, token_value=None, expires_at=None):
    token_value, token = create_personal_token(
        user,
        scopes=scopes,
        token_value=token_value,
        expires_at=expires_at,
    )

    return basic_auth(user.email or user.username, token_value), token


def xml_text(response):
    return response.data.decode("utf-8")


def hrefs_from_response(response):
    root = ElementTree.fromstring(response.data)
    hrefs = []

    for element in root.iter():
        if element.tag.endswith("href") and element.text:
            hrefs.append(element.text.strip())

    return hrefs


def create_team_with_rotation():
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Cloud OPS")
    user = create_user(unique("alice"), group, email=f"{unique('alice')}@example.com")
    add_user_to_team(team, user)

    start_at = datetime.utcnow() - timedelta(hours=1)

    create_rotation(
        team,
        name="Primary",
        users=[user],
        start_at=start_at,
        duration_seconds=24 * 3600,
    )

    return group, team, user


def first_team_event(team):
    events = list_team_caldav_events(team)
    assert events

    return events[0]


def calendar_query_body():
    return """<?xml version="1.0" encoding="utf-8" ?>
<cal:calendar-query xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag />
    <cal:calendar-data />
  </d:prop>
  <cal:filter>
    <cal:comp-filter name="VCALENDAR">
      <cal:comp-filter name="VEVENT" />
    </cal:comp-filter>
  </cal:filter>
</cal:calendar-query>
"""


def calendar_multiget_body(hrefs):
    href_xml = "\n".join(f"  <d:href>{href}</d:href>" for href in hrefs)

    return f"""<?xml version="1.0" encoding="utf-8" ?>
<cal:calendar-multiget xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag />
    <cal:calendar-data />
  </d:prop>
{href_xml}
</cal:calendar-multiget>
"""


def test_caldav_options_advertises_calendar_access(client, db):
    response = client.open("/caldav/", method="OPTIONS")

    assert response.status_code == 204
    assert "calendar-access" in response.headers["DAV"]
    assert "PROPFIND" in response.headers["Allow"]
    assert "REPORT" in response.headers["Allow"]


def test_caldav_requires_basic_auth(client, db):
    response = client.open("/caldav/", method="PROPFIND")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="IncidentRelay CalDAV"'


def test_caldav_rejects_invalid_token(client, db):
    _, _, user = create_team_with_rotation()

    response = client.open(
        "/caldav/",
        method="PROPFIND",
        headers=basic_auth(user.email, "wrong-token"),
    )

    assert response.status_code == 401


def test_caldav_rejects_token_without_calendar_scope(client, db):
    _, _, user = create_team_with_rotation()
    headers, _ = caldav_headers(user, scopes=["alerts:read"])

    response = client.open(
        "/caldav/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 401


def test_caldav_accepts_wildcard_scope(client, db):
    _, _, user = create_team_with_rotation()
    headers, _ = caldav_headers(user, scopes=["*"])

    response = client.open(
        "/caldav/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 207
    assert "calendar-home-set" in xml_text(response)


def test_caldav_rejects_expired_token(client, db):
    _, _, user = create_team_with_rotation()
    headers, _ = caldav_headers(
        user,
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )

    response = client.open(
        "/caldav/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 401


def test_caldav_rejects_revoked_token(client, db):
    _, _, user = create_team_with_rotation()
    headers, token = caldav_headers(user)

    tokens_repo.revoke_user_token(token.id, user.id)

    response = client.open(
        "/caldav/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 401


def test_caldav_marks_api_token_used(client, db):
    _, _, user = create_team_with_rotation()
    headers, token = caldav_headers(user)

    assert token.last_used_at is None

    response = client.open(
        "/caldav/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 207

    token = ApiToken.get_by_id(token.id)
    assert token.last_used_at is not None


def test_caldav_root_discovery_returns_principal_and_calendar_home(client, db):
    _, _, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    response = client.open(
        "/caldav/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 207

    body = xml_text(response)

    assert "/caldav/principals/" in body
    assert "/caldav/calendars/" in body
    assert "current-user-principal" in body
    assert "principal-URL" in body
    assert "calendar-home-set" in body
    assert "current-user-privilege-set" in body


def test_caldav_principal_returns_calendar_home(client, db):
    _, _, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/principals/{user.id}/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 207

    body = xml_text(response)

    assert f"/caldav/principals/{user.id}/" in body
    assert "/caldav/calendars/" in body
    assert "calendar-home-set" in body


def test_caldav_principal_rejects_other_user(client, db):
    group, _, user = create_team_with_rotation()
    other = create_user(unique("bob"), group, email=f"{unique('bob')}@example.com")
    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/principals/{other.id}/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 403


def test_caldav_calendar_home_lists_accessible_team_calendars_only(client, db):
    group, team, user = create_team_with_rotation()

    other_group = create_group(slug=unique("other-group"))
    other_team = create_team(other_group, slug=unique("other-team"), name="Other Team")

    headers, _ = caldav_headers(user)

    response = client.open(
        "/caldav/calendars/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 207

    body = xml_text(response)

    assert f"/caldav/calendars/teams/{team.id}/" in body
    assert "Cloud OPS on-call" in body
    assert f"/caldav/calendars/teams/{other_team.id}/" not in body
    assert "supported-calendar-component-set" in body


def test_caldav_team_calendar_depth_zero_returns_calendar_metadata(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/",
        method="PROPFIND",
        headers={
            **headers,
            "Depth": "0",
        },
    )

    assert response.status_code == 207

    body = xml_text(response)

    assert f"{team.name} on-call" in body
    assert "supported-calendar-component-set" in body
    assert "current-user-privilege-set" in body
    assert "calendar-data" not in body


def test_caldav_team_calendar_depth_one_returns_event_hrefs_and_etags(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/",
        method="PROPFIND",
        headers={
            **headers,
            "Depth": "1",
        },
    )

    assert response.status_code == 207

    body = xml_text(response)

    assert f"/caldav/calendars/teams/{team.id}/" in body
    assert ".ics" in body
    assert "getetag" in body
    assert "text/calendar" in body


def test_caldav_user_cannot_access_non_member_team(client, db):
    _, _, user = create_team_with_rotation()

    other_group = create_group(slug=unique("other-group"))
    other_team = create_team(other_group, slug=unique("other-team"), name="Other Team")

    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/calendars/teams/{other_team.id}/",
        method="PROPFIND",
        headers=headers,
    )

    assert response.status_code == 404


def test_caldav_calendar_query_report_returns_calendar_data(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/",
        method="REPORT",
        headers={
            **headers,
            "Content-Type": "application/xml",
        },
        data=calendar_query_body(),
    )

    assert response.status_code == 207

    body = xml_text(response)

    assert "calendar-data" in body
    assert "BEGIN:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body
    assert "SUMMARY:On-call:" in body


def test_caldav_empty_report_body_behaves_as_calendar_query(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/",
        method="REPORT",
        headers=headers,
        data=b"",
    )

    assert response.status_code == 207
    assert "BEGIN:VEVENT" in xml_text(response)


def test_caldav_calendar_multiget_returns_only_requested_hrefs(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    events = list_team_caldav_events(team)

    assert events

    requested_event = events[0]
    requested_href = event_href(team.id, requested_event)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/",
        method="REPORT",
        headers={
            **headers,
            "Content-Type": "application/xml",
        },
        data=calendar_multiget_body([requested_href]),
    )

    assert response.status_code == 207

    hrefs = hrefs_from_response(response)

    assert requested_href in hrefs
    assert len([href for href in hrefs if href.endswith(".ics")]) == 1
    assert "BEGIN:VEVENT" in xml_text(response)


def test_caldav_unknown_report_returns_400(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    body = """<?xml version="1.0" encoding="utf-8" ?>
<d:expand-property xmlns:d="DAV:" />
"""

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/",
        method="REPORT",
        headers={
            **headers,
            "Content-Type": "application/xml",
        },
        data=body,
    )

    assert response.status_code == 400


def test_caldav_get_calendar_object_returns_ics(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    event = first_team_event(team)
    uid = event_uid(event)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/{uid}.ics",
        method="GET",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.mimetype == "text/calendar"
    assert response.headers["ETag"]

    body = unfold_ics(response.data.decode("utf-8"))

    assert "BEGIN:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body
    assert f"UID:{uid}" in body
    assert "SUMMARY:On-call:" in body


def test_caldav_head_calendar_object_returns_headers_without_body(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    event = first_team_event(team)
    uid = event_uid(event)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/{uid}.ics",
        method="HEAD",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.mimetype == "text/calendar"
    assert response.headers["ETag"]
    assert response.data == b""


def test_caldav_get_missing_event_returns_404(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/missing.ics",
        method="GET",
        headers=headers,
    )

    assert response.status_code == 404


def test_caldav_proppatch_team_calendar_is_accepted_as_noop(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    body = """<?xml version="1.0" encoding="utf-8" ?>
<d:propertyupdate xmlns:d="DAV:">
  <d:set>
    <d:prop>
      <d:displayname>Custom name</d:displayname>
    </d:prop>
  </d:set>
</d:propertyupdate>
"""

    response = client.open(
        f"/caldav/calendars/teams/{team.id}/",
        method="PROPPATCH",
        headers={
            **headers,
            "Content-Type": "application/xml",
        },
        data=body,
    )

    assert response.status_code == 207
    assert "multistatus" in xml_text(response)
    assert f"/caldav/calendars/teams/{team.id}/" in xml_text(response)


def test_caldav_proppatch_root_calendar_home_and_principal_are_noops(client, db):
    _, _, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    paths = [
        "/caldav/",
        "/caldav/calendars/",
        f"/caldav/principals/{user.id}/",
    ]

    for path in paths:
        response = client.open(
            path,
            method="PROPPATCH",
            headers=headers,
            data=b"<d:propertyupdate xmlns:d=\"DAV:\" />",
        )

        assert response.status_code == 207


def test_caldav_write_methods_are_forbidden(client, db):
    _, team, user = create_team_with_rotation()
    headers, _ = caldav_headers(user)

    paths_and_methods = [
        ("/caldav/", "PUT"),
        ("/caldav/", "DELETE"),
        ("/caldav/", "MKCALENDAR"),
        (f"/caldav/calendars/teams/{team.id}/", "PUT"),
        (f"/caldav/calendars/teams/{team.id}/", "DELETE"),
        (f"/caldav/calendars/teams/{team.id}/", "MKCALENDAR"),
    ]

    for path, method in paths_and_methods:
        response = client.open(
            path,
            method=method,
            headers=headers,
            data=b"",
        )

        assert response.status_code == 403
