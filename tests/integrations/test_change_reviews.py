"""Manual decisions, safe projections, optimistic concurrency and atomic writes."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from peewee import IntegrityError

from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.models import (
    AlertGroupEpisode,
    AuditLog,
    ChangeAlertGroupCorrelation,
    ChangeIncidentLink,
    Incident,
    IncidentEvent,
    IncidentNotificationDelivery,
    Service,
    TeamUser,
)
from app.services.change_intelligence import incident_links, reviewing
from app.services.change_intelligence.catalog import graph_change
from tests.factories import add_user_to_team, create_group, create_team, create_user
from tests.integrations.test_change_correlation import (
    episode_for,
    intake,
    operation,
    opt_in,
    request_change,
    run_change,
    setup_identity,
)
from tests.integrations.test_change_integration_groups import headers
from tests.integrations.test_changes_read import changes, personal

__all__ = ["intake", "setup_identity", "changes"]


@pytest.fixture
def review_case(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake, title="PRIVATE deployment")
    run_change(change)
    user = create_user(group=service.team.group, group_role="viewer")
    add_user_to_team(service.team, user, role="responder")
    incident = Incident.create(team=service.team_id, title="Checkout investigation")
    return SimpleNamespace(
        service=service,
        episode=episode,
        change=change,
        user=user,
        incident=incident,
        row=ChangeAlertGroupCorrelation.get(),
    )


def base(case):
    return f"/api/changes/{case.change.uid}"


def review_body(case, **updates):
    return {
        "row_version": case.row.row_version,
        "decision": "confirmed",
        "relation_type": "confirmed_cause",
        "note": "Verified by the responder",
        "evidence_version": reviewing.evidence_version(case.row),
        **updates,
    }


def link_body(case, **updates):
    return {
        "change_uid": str(case.change.uid),
        "relation_type": "context",
        "note": "Relevant to this investigation",
        **updates,
    }


def review_url(case):
    return base(case) + f"/correlations/{case.row.id}/review"


def incident_url(case):
    return f"/api/incidents/{case.incident.id}/changes"


@pytest.mark.parametrize("decision", ["confirmed", "rejected"])
def test_review_is_versioned_and_survives_recalculation(client, review_case, decision):
    case = review_case
    auth = headers(case.user)
    response = client.post(
        review_url(case), headers=auth, json=review_body(case, decision=decision)
    )
    assert response.status_code == 200, response.json
    assert response.json["review_status"] == decision
    assert response.json["row_version"] == 2
    evidence = response.json["review_evidence"]
    assert evidence["suggestion"]["score"] > 0
    assert "path" not in json.dumps(evidence)
    stale = client.post(review_url(case), headers=auth, json=review_body(case))
    assert stale.status_code == 409
    assert stale.json["reason"] == "relation_changed"
    request_change(case.change)
    run_change(case.change, "refresh_correlations")
    row = ChangeAlertGroupCorrelation.get_by_id(case.row.id)
    assert row.review_evidence == evidence
    assert row.review_status == decision and row.row_version == 2
    assert (
        AuditLog.select().where(AuditLog.action == "change.correlation.review").count()
        == 1
    )


def test_stale_suggestion_cannot_be_confirmed(client, review_case):
    case = review_case
    with graph_change():
        pass
    response = client.post(
        review_url(case), headers=headers(case.user), json=review_body(case)
    )
    assert response.status_code == 409
    assert response.json["reason"] == "suggestion_stale"
    listed = client.get(base(case) + "/correlations", headers=headers(case.user)).json
    assert listed["items"][0]["suggestion_current"] is False
    assert listed["items"][0]["score"] is None


@pytest.mark.parametrize(
    "relation", ["mitigation", "context", "confirmed_cause", "potential_cause"]
)
def test_manual_relation_without_candidate_or_enabled_policy(
    client, review_case, relation
):
    case = review_case
    episode = episode_for(case.service, start=utc_now() - timedelta(days=30))
    Service.update(change_correlation_enabled=False).where(
        Service.id == case.service.id
    ).execute()
    response = client.post(
        base(case) + "/correlations",
        headers=headers(case.user),
        json={
            "episode_id": episode.id,
            "relation_type": relation,
            "note": "Historical investigation",
        },
    )
    assert response.status_code == 201, response.json
    row = ChangeAlertGroupCorrelation.get_by_id(response.json["id"])
    assert row.score is None and row.active is False
    assert row.review_status == "confirmed" and row.relation_type == relation
    assert row.review_evidence["suggestion"]["score"] is None
    assert row.episode_id != case.row.episode_id
    assert (
        ChangeAlertGroupCorrelation.get_by_id(case.row.id).review_status == "suggested"
    )


def test_reader_cannot_review_and_foreign_targets_are_hidden(client, review_case):
    case = review_case
    TeamUser.update(role="viewer").where(TeamUser.user == case.user.id).execute()
    assert (
        client.get(base(case) + "/correlations", headers=headers(case.user)).json[
            "items"
        ][0]["can_review"]
        is False
    )
    assert (
        client.post(
            review_url(case), headers=headers(case.user), json=review_body(case)
        ).status_code
        == 403
    )
    outsider = create_user(group=create_group())
    hidden = client.post(
        review_url(case), headers=headers(outsider), json=review_body(case)
    )
    missing = client.post(
        base(case) + "/correlations/2147483647/review",
        headers=headers(outsider),
        json=review_body(case),
    )
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json == missing.json


@pytest.mark.parametrize(
    "field,value",
    [
        ("row_version", 0),
        ("row_version", True),
        ("decision", "approved"),
        ("relation_type", "automatic"),
        ("note", "  "),
        ("note", "x" * 2001),
    ],
)
def test_invalid_review_is_rejected(client, review_case, field, value):
    response = client.post(
        review_url(review_case),
        headers=headers(review_case.user),
        json=review_body(review_case, **{field: value}),
    )
    assert response.status_code == 400
    assert ChangeAlertGroupCorrelation.get_by_id(review_case.row.id).row_version == 1


def test_review_audit_failure_rolls_back_decision(client, review_case, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(reviewing, "write_audit", fail)
    response = client.post(
        review_url(review_case),
        headers=headers(review_case.user),
        json=review_body(review_case),
    )
    assert response.status_code == 500
    row = ChangeAlertGroupCorrelation.get_by_id(review_case.row.id)
    assert row.row_version == 1 and row.review_evidence is None
    assert row.review_status == "suggested"


def test_incident_add_duplicate_edit_remove_restore(client, review_case):
    case = review_case
    auth = headers(case.user)
    url = incident_url(case)
    created = client.post(url, headers=auth, json=link_body(case))
    assert created.status_code == 201, created.json
    duplicate = client.post(url, headers=auth, json=link_body(case))
    assert duplicate.status_code == 200 and duplicate.json == created.json
    assert IncidentEvent.select().count() == 1
    conflicting = client.post(
        url, headers=auth, json=link_body(case, relation_type="mitigation")
    )
    assert conflicting.status_code == 409
    assert conflicting.json["reason"] == "incident_role_conflict"
    item = url + f"/{created.json['id']}"
    edited = client.patch(
        item,
        headers=auth,
        json={
            "row_version": 1,
            "relation_type": "mitigation",
            "note": "Fixed checkout",
        },
    )
    assert edited.status_code == 200 and edited.json["row_version"] == 2
    stale = client.delete(
        item, headers=auth, json={"row_version": 1, "note": "Old decision"}
    )
    assert stale.status_code == 409
    assert stale.json["reason"] == "incident_link_changed"
    removed = client.delete(
        item, headers=auth, json={"row_version": 2, "note": "Wrong incident"}
    )
    assert removed.status_code == 200 and removed.json["row_version"] == 3
    assert client.get(url, headers=auth).json["pagination"]["total"] == 0
    assert (
        client.get(url + "?include_removed=true", headers=auth).json["pagination"][
            "total"
        ]
        == 1
    )
    duplicate = client.post(url, headers=auth, json=link_body(case))
    assert duplicate.status_code == 409
    assert duplicate.json["reason"] == "incident_link_removed"
    restored = client.post(url, headers=auth, json=link_body(case, row_version=3))
    assert restored.status_code == 201 and restored.json["id"] == created.json["id"]
    assert restored.json["row_version"] == 4 and restored.json["removed_at"] is None
    incident = Incident.get_by_id(case.incident.id)
    assert incident.row_version == 5 and incident.workflow_status == "declared"
    assert IncidentEvent.select().count() == 4
    assert IncidentNotificationDelivery.select().count() == 0
    assert "PRIVATE" not in json.dumps([event.data for event in IncidentEvent.select()])


@pytest.mark.parametrize("failure", ["link", "event", "audit"])
def test_incident_failure_rolls_back_link_event_and_version(
    client, review_case, monkeypatch, failure
):
    def fail(*args, **kwargs):
        raise RuntimeError("write unavailable")

    if failure == "link":
        monkeypatch.setattr(ChangeIncidentLink, "create", fail)
    elif failure == "event":
        monkeypatch.setattr(incident_core_repo, "create_event", fail)
    else:
        monkeypatch.setattr(incident_links, "write_audit", fail)
    response = client.post(
        incident_url(review_case),
        headers=headers(review_case.user),
        json=link_body(review_case),
    )
    assert response.status_code == 500
    assert ChangeIncidentLink.select().count() == 0
    assert IncidentEvent.select().count() == 0
    assert Incident.get_by_id(review_case.incident.id).row_version == 1


def test_safe_reader_cannot_recover_private_change_data_from_incident(client, changes):
    user = changes["foreign"]
    TeamUser.update(role="responder").where(TeamUser.user == user.id).execute()
    incident = Incident.create(
        team=changes["service"].team_id, title="Visible incident"
    )
    url = f"/api/incidents/{incident.id}/changes"
    response = client.post(
        url,
        headers=headers(user),
        json={
            "change_uid": str(changes["change"].uid),
            "relation_type": "context",
            "note": "Investigating",
        },
    )
    assert response.status_code == 201, response.json
    assert response.json["change"]["projection"] == "safe"
    assert "PRIVATE" not in json.dumps(response.json)
    assert "PRIVATE" not in json.dumps(client.get(url, headers=headers(user)).json)
    with graph_change():
        pass
    assert client.get(url, headers=headers(user)).json["pagination"]["total"] == 0
    assert (
        client.patch(
            url + f"/{response.json['id']}",
            headers=headers(user),
            json={
                "row_version": 1,
                "relation_type": "mitigation",
                "note": "Cannot bypass revocation",
            },
        ).status_code
        == 404
    )


def test_links_restrict_parent_deletion_even_after_removal(client, review_case, db):
    case = review_case
    response = client.post(
        incident_url(case), headers=headers(case.user), json=link_body(case)
    )
    assert response.status_code == 201
    link = ChangeIncidentLink.get()
    ChangeIncidentLink.update(removed_at=utc_now()).where(
        ChangeIncidentLink.id == link.id
    ).execute()
    for parent in (case.incident, case.change):
        with pytest.raises(IntegrityError), db.atomic():
            parent.delete_instance()
    assert ChangeIncidentLink.select().count() == 1


def test_target_pagination_excludes_other_teams_and_does_not_create_episodes(
    client, review_case
):
    case = review_case
    hidden_team = create_team(create_group())
    from tests.factories import create_service

    hidden = episode_for(create_service(hidden_team))
    before = AlertGroupEpisode.select().count()
    result = client.get(
        base(case) + "/correlation-targets?page_size=1", headers=headers(case.user)
    )
    assert result.status_code == 200
    assert result.json["pagination"]["total"] == 1
    assert result.json["items"][0]["id"] != hidden.id
    assert AlertGroupEpisode.select().count() == before


def test_recalculated_evidence_requires_reload_even_with_same_manual_version(
    client, review_case
):
    case = review_case
    payload = review_body(case)
    ChangeAlertGroupCorrelation.update(score=case.row.score - 1).where(
        ChangeAlertGroupCorrelation.id == case.row.id
    ).execute()
    response = client.post(review_url(case), headers=headers(case.user), json=payload)
    assert response.status_code == 409
    assert response.json["reason"] == "evidence_changed"
    assert ChangeAlertGroupCorrelation.get_by_id(case.row.id).row_version == 1


def test_existing_episode_relation_conflict_does_not_change_decision(
    client, review_case
):
    case = review_case
    response = client.post(
        base(case) + "/correlations",
        headers=headers(case.user),
        json={
            "episode_id": case.episode.id,
            "relation_type": "context",
            "note": "Duplicate",
        },
    )
    assert response.status_code == 409
    assert response.json["error"] == "conflict"
    assert response.json["reason"] == "relation_exists"
    assert ChangeAlertGroupCorrelation.select().count() == 1
    assert (
        ChangeAlertGroupCorrelation.get_by_id(case.row.id).review_status == "suggested"
    )


@pytest.mark.parametrize("removed", [True, False])
def test_restore_conflict_distinguishes_newer_version_from_missing_link(
    client, review_case, removed
):
    case = review_case
    auth = headers(case.user)
    url = incident_url(case)
    if removed:
        created = client.post(url, headers=auth, json=link_body(case))
        result = client.delete(
            url + f"/{created.json['id']}",
            headers=auth,
            json={"row_version": 1, "note": "Removed during review"},
        )
        assert result.status_code == 200
    version = Incident.get_by_id(case.incident.id).row_version
    event_count = IncidentEvent.select().count()
    audit_count = AuditLog.select().count()
    response = client.post(url, headers=auth, json=link_body(case, row_version=1))
    assert response.status_code == 409
    assert response.json["reason"] == (
        "incident_link_changed" if removed else "incident_link_missing"
    )
    assert Incident.get_by_id(case.incident.id).row_version == version
    assert IncidentEvent.select().count() == event_count
    assert AuditLog.select().count() == audit_count
    if removed:
        assert ChangeIncidentLink.get().removed_at is not None
    else:
        assert ChangeIncidentLink.select().count() == 0


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_editing_removed_link_returns_restore_guidance(client, review_case, method):
    case = review_case
    auth = headers(case.user)
    url = incident_url(case)
    created = client.post(url, headers=auth, json=link_body(case))
    item = url + f"/{created.json['id']}"
    assert (
        client.delete(
            item, headers=auth, json={"row_version": 1, "note": "No longer relevant"}
        ).status_code
        == 200
    )
    payload = {"row_version": 1, "note": "Old dialog"}
    if method == "patch":
        payload["relation_type"] = "mitigation"
    response = getattr(client, method)(item, headers=auth, json=payload)
    assert response.status_code == 409
    assert response.json["reason"] == "incident_link_removed"
    assert ChangeIncidentLink.get().row_version == 2
    assert IncidentEvent.select().count() == 2


def test_incident_version_conflict_is_explained_and_rolls_back(
    client, review_case, monkeypatch
):
    def conflict(*args, **kwargs):
        raise incident_core_repo.IncidentConflictError("concurrent update")

    case = review_case
    audit_count = AuditLog.select().count()
    monkeypatch.setattr(incident_core_repo, "compare_and_swap", conflict)
    response = client.post(
        incident_url(case), headers=headers(case.user), json=link_body(case)
    )
    assert response.status_code == 409
    assert response.json["reason"] == "incident_changed"
    assert ChangeIncidentLink.select().count() == 0
    assert IncidentEvent.select().count() == 0
    assert AuditLog.select().count() == audit_count
    assert Incident.get_by_id(case.incident.id).row_version == case.incident.row_version


def test_explicit_manual_mitigation_can_replace_stale_candidate(client, review_case):
    case = review_case
    with graph_change():
        pass
    response = client.post(
        review_url(case),
        headers=headers(case.user),
        json=review_body(
            case,
            manual=True,
            relation_type="mitigation",
            evidence_version=None,
        ),
    )
    assert response.status_code == 200, response.json
    assert response.json["relation_type"] == "mitigation"
    assert response.json["review_evidence"]["suggestion"]["score"] is None


@pytest.mark.parametrize("target", ["alert", "incident"])
def test_personal_tokens_need_both_write_scopes(client, review_case, target):
    case = review_case
    scope = "alerts:write" if target == "alert" else "incidents:write"
    url = review_url(case) if target == "alert" else incident_url(case)
    payload = review_body(case) if target == "alert" else link_body(case)
    for scopes in (["changes:write"], [scope], ["changes:read", scope]):
        response = client.post(url, headers=personal(case.user, scopes), json=payload)
        assert response.status_code == 403, response.json
    response = client.post(
        url, headers=personal(case.user, ["changes:write", scope]), json=payload
    )
    assert response.status_code in (200, 201), response.json


def test_scoped_admin_token_cannot_link_an_out_of_scope_incident(client, review_case):
    case = review_case
    admin = create_user(is_admin=True)
    foreign = Incident.create(
        team=create_team(case.service.team.group), title="Other team"
    )
    auth = personal(
        admin, ["changes:write", "incidents:write"], team_id=case.service.team_id
    )
    response = client.post(
        f"/api/incidents/{foreign.id}/changes", headers=auth, json=link_body(case)
    )
    assert response.status_code == 404
    assert ChangeIncidentLink.select().count() == 0


def test_manual_create_audit_failure_leaves_no_relation(
    client, review_case, monkeypatch
):
    episode = episode_for(review_case.service)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(reviewing, "write_audit", fail)
    response = client.post(
        base(review_case) + "/correlations",
        headers=headers(review_case.user),
        json={
            "episode_id": episode.id,
            "relation_type": "mitigation",
            "note": "Fixed",
        },
    )
    assert response.status_code == 500
    assert (
        not ChangeAlertGroupCorrelation.select()
        .where(ChangeAlertGroupCorrelation.episode == episode.id)
        .exists()
    )


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_incident_edit_failure_preserves_previous_link(
    client, review_case, monkeypatch, method
):
    case = review_case
    added = client.post(
        incident_url(case), headers=headers(case.user), json=link_body(case)
    )
    assert added.status_code == 201

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(incident_links, "write_audit", fail)
    payload = {"row_version": 1, "note": "Reconsidering"}
    if method == "PATCH":
        payload["relation_type"] = "mitigation"
    response = client.open(
        incident_url(case) + f"/{added.json['id']}",
        method=method,
        headers=headers(case.user),
        json=payload,
    )
    assert response.status_code == 500
    row = ChangeIncidentLink.get()
    assert (
        row.row_version == 1
        and row.relation_type == "context"
        and row.removed_at is None
    )
    assert IncidentEvent.select().count() == 1
    assert Incident.get_by_id(case.incident.id).row_version == 2
