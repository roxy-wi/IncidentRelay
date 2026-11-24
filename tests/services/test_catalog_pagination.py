"""Coverage for the paged catalog APIs used by the two services tables."""

from datetime import timedelta
from uuid import uuid4

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db.models import BusinessService, ServiceReadinessState
from tests.factories import add_user_to_team, create_group, create_service, create_team, create_user


def viewer_headers(team):
    user = create_user(group=team.group, group_role="viewer")
    add_user_to_team(team, user, role="viewer")
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_technical_service_pages_search_readiness_and_scope(client, db):
    team = create_team(create_group())
    headers = viewer_headers(team)
    other = create_team(create_group())
    hidden = create_service(other, name="Hidden")
    first = create_service(team, name="API")
    second = create_service(team, name="API", enabled=False)
    last = create_service(team, name="Система 100%_A", status="major_outage", criticality="critical")
    ServiceReadinessState.create(service=last, status="not_ready", score=37, batch_uid=uuid4())

    def fetch(**args):
        response = client.get("/api/services", headers=headers, query_string={"page_size": 1, **args})
        assert response.status_code == 200
        return response.get_json()

    assert fetch()["items"][0]["id"] == first.id
    assert fetch(page=2)["items"][0]["id"] == second.id
    result = fetch(page=999)
    assert result["items"][0]["id"] == last.id
    assert result["summary"] == {"total": 3, "affected": 1, "major": 1, "operational": 1}
    assert result["pagination"] == dict(page=3, page_size=1, total_items=3, total_pages=3,
                                        has_next=False, has_prev=True, **{"from": 3, "to": 3})

    result = fetch(page=2, search="сИСТЕМА 100%_", readiness="not_ready", status="major_outage",
                   criticality="critical")
    assert [item["id"] for item in result["items"]] == [last.id]
    assert result["pagination"]["page"] == 1
    assert result["summary"]["total"] == 3
    assert fetch(search="100%Z")["items"] == []
    assert fetch(search="%_")["pagination"]["total_items"] == 1
    assert fetch(service_id=last.id)["items"][0]["id"] == last.id
    assert fetch(readiness="not_evaluated")["pagination"]["total_items"] == 2
    assert fetch(service_id=hidden.id)["items"] == []
    empty = fetch(search="Hidden", page_size=10000)
    assert empty["items"] == []
    assert empty["pagination"]["from"] == empty["pagination"]["to"] == 0
    assert empty["pagination"]["page_size"] == 100
    assert client.get(f"/api/services?page=1&team_id={other.id}", headers=headers).status_code == 403
    legacy = client.get("/api/services", headers=headers).get_json()
    assert [item["id"] for item in legacy] == [first.id, second.id, last.id]


def test_business_service_pages_filters_expiry_and_scope(client, db):
    team = create_team(create_group())
    group = team.group
    headers = viewer_headers(team)
    other = create_group()
    BusinessService.create(group=other, name="Hidden", slug="hidden")
    first = BusinessService.create(group=group, name="Catalog", slug="first", owner_team=team,
                                   public=False, manual_status="degraded")
    second = BusinessService.create(group=group, name="Catalog", slug="second", public=True,
                                    manual_status="operational")
    BusinessService.create(group=group, name="Unused", slug="unused", enabled=False)

    def fetch(**args):
        response = client.get("/api/business-services", headers=headers,
                              query_string={"group_id": group.id, "page_size": 1, **args})
        assert response.status_code == 200
        return response.get_json()

    assert fetch()["items"][0]["id"] == first.id
    assert fetch(page=2)["items"][0]["id"] == second.id
    result = fetch(page=2, search=team.slug, status="degraded", visibility="private")
    assert [item["id"] for item in result["items"]] == [first.id]
    assert result["summary"] == {"total": 2, "operational": 1, "affected": 1, "public": 1}
    assert result["pagination"]["total_items"] == result["pagination"]["page"] == 1

    second.manual_status_until = utc_now() - timedelta(seconds=1)
    second.save(only=[BusinessService.manual_status_until])
    assert fetch(status="operational")["items"] == []
    assert fetch(status="unknown")["items"][0]["id"] == second.id
    assert fetch(public="true")["summary"]["total"] == 1
    assert fetch(search="Hidden")["items"] == []
    first.manual_status = "maintenance"
    first.save(only=[BusinessService.manual_status])
    assert fetch(refresh_status="true", status="maintenance")["items"][0]["id"] == first.id
    base = "/api/business-services"
    assert client.get(base + "?page=1", headers=headers).status_code == 400
    assert client.get(base + f"?page=1&group_id={other.id}", headers=headers).status_code == 403
    legacy = client.get(base, headers=headers, query_string={"group_id": group.id}).get_json()
    assert [item["id"] for item in legacy] == [first.id, second.id]
