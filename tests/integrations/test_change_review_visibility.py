"""Review history remains scoped and attached to its original alert episode."""

import json
from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertGroupEpisode,
    AuditLog,
    ChangeAlertGroupCorrelation,
    UserGroup,
    TeamUser,
)
from app.services.alerts import lifecycle
from app.services.alerts.retention import cleanup_alert_history
from app.services.orchestration.runtime import RuntimeResult
from tests.factories import add_user_to_team, create_route, unique
from tests.integrations.test_change_reviews import (
    base,
    changes,
    episode_for,
    headers,
    intake,
    review_body,
    review_case,
    review_url,
    request_change,
    run_change,
    setup_identity,
)

__all__ = ["changes", "intake", "review_case", "setup_identity"]


def test_full_review_snapshot_never_leaks_to_safe_reader_or_shared_audit(
    client, changes
):
    owner = changes["owner"]
    service = changes["service"]
    UserGroup.create(
        user=owner, group=service.team.group_id, role="viewer", active=True
    )
    add_user_to_team(service.team, owner, role="responder")
    TeamUser.update(role="responder").where(
        TeamUser.user == changes["foreign"].id
    ).execute()
    episode = episode_for(service)
    url = f"/api/changes/{changes['change'].uid}/correlations"
    created = client.post(
        url,
        headers=headers(owner),
        json={
            "episode_id": episode.id,
            "relation_type": "context",
            "note": "Investigating this relation",
        },
    )
    assert created.status_code == 201, created.json
    assert "PRIVATE" in json.dumps(created.json["review_evidence"])
    safe = client.get(url, headers=headers(changes["foreign"]))
    assert safe.status_code == 200 and safe.json["pagination"]["total"] == 1
    assert "PRIVATE" not in json.dumps(safe.json)
    audit = AuditLog.get(AuditLog.action == "change.correlation.create")
    assert "PRIVATE" not in json.dumps(audit.data)
    # Changing a decision as a safe reader still cannot expose the original snapshot.
    reconsidered = client.post(
        url + f"/{created.json['id']}/review",
        headers=headers(changes["foreign"]),
        json={
            "row_version": 1,
            "decision": "rejected",
            "relation_type": "context",
            "note": "Unrelated",
        },
    )
    assert reconsidered.status_code == 200
    assert "PRIVATE" not in json.dumps(reconsidered.json)
    assert reconsidered.json["review_evidence"]["note"] == "Unrelated"


def test_retention_keeps_a_reviewed_episode_and_its_evidence(client, review_case):
    case = review_case
    response = client.post(
        review_url(case), headers=headers(case.user), json=review_body(case)
    )
    assert response.status_code == 200
    old = utc_now() - timedelta(days=40)
    Alert.update(status="resolved", resolved_at=old).where(
        Alert.group == case.episode.alert_group_id
    ).execute()
    AlertGroup.update(status="resolved", resolved_at=old).where(
        AlertGroup.id == case.episode.alert_group_id
    ).execute()
    cleanup_alert_history(retention_days=7)
    assert AlertGroupEpisode.get_by_id(case.episode.id)
    assert (
        ChangeAlertGroupCorrelation.get_by_id(case.row.id).review_evidence
        == response.json["review_evidence"]
    )


def test_genuine_reopen_does_not_inherit_previous_review(
    client, review_case, monkeypatch
):
    case = review_case
    route = create_route(
        case.service.team,
        source="alertmanager",
        group_by=["alertname"],
        service=case.service,
    )
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": unique("review-cycle"),
        "dedup_key": unique("review-key"),
        "title": "Recurring checkout failure",
        "severity": "critical",
        "status": "firing",
        "labels": {"alertname": "Checkout"},
        "payload": {},
    }
    first = lifecycle.upsert_alert(dict(data))
    first_episode = first.group.current_episode_id
    created = client.post(
        base(case) + "/correlations",
        headers=headers(case.user),
        json={
            "episode_id": first_episode,
            "relation_type": "mitigation",
            "note": "First occurrence was fixed",
        },
    )
    assert created.status_code == 201
    lifecycle.upsert_alert(dict(data, status="resolved"))
    reopened = lifecycle.upsert_alert(dict(data))
    assert reopened.group.id == first.group.id
    assert reopened.group.current_episode_id != first_episode
    request_change(case.change)
    run_change(case.change, "refresh_correlations")
    original = ChangeAlertGroupCorrelation.get_by_id(created.json["id"])
    new = ChangeAlertGroupCorrelation.get(
        ChangeAlertGroupCorrelation.episode == reopened.group.current_episode_id
    )
    assert (
        original.review_status == "confirmed" and original.relation_type == "mitigation"
    )
    assert new.review_status == "suggested" and new.review_evidence is None
    assert original.review_evidence == created.json["review_evidence"]
