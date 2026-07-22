from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.crypto import decrypt_json, decrypt_secret
from app.modules.db.models import (
    AutomationExecution,
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationIntakeToken,
    OrchestrationWebhookAction,
)
from app.modules.db.orchestrations_repo import (
    OrchestrationValidationError,
    create_orchestration,
    get_or_create_draft,
    publish_draft,
    replace_draft_rules,
    set_runtime_state,
)
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.runtime import attach_runtime_executions, run_event_orchestration
from app.services.orchestration import webhooks as webhook_service
from app.services.orchestration.webhooks import (
    WebhookDeliveryError,
    WebhookResponse,
    WebhookSecurityError,
    WebhookValidationError,
    create_webhook_action,
    deliver_webhook,
    enqueue_execution_webhooks,
    process_due_webhooks,
    resolve_webhook_target,
    serialize_webhook_action,
)
from tests.factories import create_group, create_route, create_team, create_user


@pytest.fixture(autouse=True)
def orchestration_webhook_tables(db):
    db.create_tables(
        [
            EventOrchestration,
            EventOrchestrationVersion,
            EventOrchestrationRule,
            OrchestrationIntakeToken,
            OrchestrationExecution,
            OrchestrationWebhookAction,
            AutomationExecution,
        ],
        safe=True,
    )
    AutomationExecution.delete().execute()
    OrchestrationWebhookAction.delete().execute()
    OrchestrationExecution.delete().execute()
    EventOrchestrationRule.delete().execute()
    EventOrchestrationVersion.delete().execute()
    OrchestrationIntakeToken.delete().execute()
    EventOrchestration.delete().execute()
    yield


def _publish(group, action_id, *, mode="active"):
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name=f"webhook-{mode}",
        scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [
            {
                "name": "enqueue diagnostics",
                "condition_tree": {},
                "actions": [
                    {"type": "enqueue_webhook", "action_id": action_id},
                ],
                "processing_mode": "continue",
            }
        ],
    )
    publish_draft(orchestration.id, actor_id=user.id)
    return set_runtime_state(
        orchestration.id,
        enabled=True,
        mode=mode,
        compatibility_mode="hybrid",
    )


def _event(route, dedup="webhook-1"):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": dedup,
        "dedup_key": dedup,
        "title": "Database unavailable",
        "message": "connection failed",
        "severity": "critical",
        "status": "firing",
        "labels": {"environment": "prod"},
        "payload": {},
    }


def test_webhook_action_encrypts_headers_and_serializes_safely(db):
    group = create_group()
    action = create_webhook_action(
        group_id=group.id,
        name="diagnostics",
        url="https://hooks.example.test/diagnostics",
        headers={"Authorization": "Bearer top-secret"},
        body_template='{"title":"{{ event.title }}"}',
    )

    assert "top-secret" not in action.headers_encrypted
    assert decrypt_json(action.headers_encrypted)["Authorization"] == "Bearer top-secret"
    payload = serialize_webhook_action(action)
    assert payload["has_headers"] is True
    assert "headers" not in payload


def test_webhook_action_rejects_secret_query_parameters(db):
    group = create_group()
    with pytest.raises(WebhookValidationError, match="encrypted headers"):
        create_webhook_action(
            group_id=group.id,
            name="secret-in-url",
            url="https://example.test/hook?token=must-not-be-stored",
        )


def test_webhook_action_rejects_http_by_default(db):
    group = create_group()
    with pytest.raises(WebhookValidationError, match="HTTPS"):
        create_webhook_action(
            group_id=group.id,
            name="unsafe",
            url="http://example.test/hook",
        )


def test_publication_rejects_webhook_action_from_another_group(db):
    owner_group = create_group(slug="owner")
    foreign_group = create_group(slug="foreign")
    action = create_webhook_action(
        group_id=foreign_group.id,
        name="foreign",
        url="https://example.test/hook",
    )
    user = create_user(group=owner_group)
    orchestration = create_orchestration(
        group_id=owner_group.id,
        name="invalid-reference",
        scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [{
            "name": "bad",
            "condition_tree": {},
            "actions": [{"type": "enqueue_webhook", "action_id": action.id}],
        }],
    )

    with pytest.raises(OrchestrationValidationError, match="another group"):
        publish_draft(orchestration.id, actor_id=user.id)


def test_publication_rejects_disabled_webhook_action(db):
    group = create_group()
    action = create_webhook_action(
        group_id=group.id,
        name="disabled",
        url="https://example.test/hook",
        enabled=False,
    )
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="disabled-reference",
        scope="global",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [{
            "name": "disabled",
            "condition_tree": {},
            "actions": [{"type": "enqueue_webhook", "action_id": action.id}],
        }],
    )

    with pytest.raises(OrchestrationValidationError, match="disabled"):
        publish_draft(orchestration.id, actor_id=user.id)


def test_lifecycle_queues_applied_webhook_once_with_encrypted_snapshot(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    action = create_webhook_action(
        group_id=group.id,
        name="diagnostics",
        url="https://hooks.example.test/diagnostics",
        headers={
            "Authorization": "Bearer top-secret",
            "X-Alert-Title": "{{ event.title }}",
        },
        body_template='{"title":"{{ event.title }}","severity":"{{ event.severity }}"}',
    )
    _publish(group, action.id)

    result = upsert_alert(_event(route))

    assert result.group is not None
    queued = AutomationExecution.get()
    assert queued.status == "pending"
    assert queued.alert_group_id == result.group.id
    assert queued.action_id == action.id
    assert queued.orchestration_execution.alert_group_id == result.group.id
    assert "top-secret" not in queued.request_headers_encrypted
    headers = decrypt_json(queued.request_headers_encrypted)
    assert headers["Authorization"] == "Bearer top-secret"
    assert headers["X-Alert-Title"] == "Database unavailable"
    assert headers["Idempotency-Key"] == queued.idempotency_key
    assert decrypt_secret(queued.request_body_encrypted) == (
        '{"title":"Database unavailable","severity":"critical"}'
    )

    assert enqueue_execution_webhooks(
        queued.orchestration_execution_id,
        alert_group_id=result.group.id,
    ) == 0
    assert AutomationExecution.select().count() == 1


def test_shadow_execution_never_queues_webhook(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    action = create_webhook_action(
        group_id=group.id,
        name="shadow",
        url="https://example.test/hook",
    )
    _publish(group, action.id, mode="shadow")
    event = _event(route, "shadow-webhook")

    runtime = run_event_orchestration(event)
    attach_runtime_executions(runtime)

    assert runtime.steps[0].applied is False
    assert AutomationExecution.select().count() == 0


def test_resolver_blocks_loopback_and_mixed_dns_answers(monkeypatch):
    monkeypatch.setattr(
        "app.services.orchestration.webhooks.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("203.0.113.10", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )

    with pytest.raises(WebhookSecurityError, match="blocked network"):
        resolve_webhook_target("https://example.test/hook")


def test_resolver_allows_explicit_private_network_allowlist(monkeypatch):
    monkeypatch.setattr(
        "app.services.orchestration.webhooks.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.20.30.40", 443))],
    )
    monkeypatch.setattr(
        "app.services.orchestration.webhooks.Config.ORCHESTRATION_WEBHOOK_PRIVATE_NETWORK_ALLOWLIST",
        "10.20.0.0/16",
    )

    parsed, address, port = resolve_webhook_target(
        "https://internal.example.test/hook",
        private_network_policy="allowlist",
    )

    assert parsed.hostname == "internal.example.test"
    assert address == "10.20.30.40"
    assert port == 443


def test_https_request_pins_resolved_ip_and_preserves_tls_hostname(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200
        headers = {}

        def read(self, **kwargs):
            return b"ok"

        def release_conn(self):
            captured["released"] = True

    class FakePool:
        def __init__(self, host, **kwargs):
            captured["host"] = host
            captured["pool_kwargs"] = kwargs

        def urlopen(self, method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["headers"] = kwargs["headers"]
            return FakeResponse()

        def close(self):
            captured["closed"] = True

    parsed = webhook_service.urlsplit("https://hooks.example.test:8443/run?q=1")
    monkeypatch.setattr(
        webhook_service,
        "resolve_webhook_target",
        lambda *args, **kwargs: (parsed, "198.51.100.25", 8443),
    )
    monkeypatch.setattr(webhook_service.urllib3, "HTTPSConnectionPool", FakePool)

    status, headers, payload = webhook_service._request_once(
        "https://hooks.example.test:8443/run?q=1",
        method="POST",
        headers={"X-Test": "yes"},
        body=b"{}",
        timeout_seconds=5,
        private_network_policy="deny",
    )

    assert status == 200
    assert payload == b"ok"
    assert captured["host"] == "198.51.100.25"
    assert captured["pool_kwargs"]["server_hostname"] == "hooks.example.test"
    assert captured["pool_kwargs"]["assert_hostname"] == "hooks.example.test"
    assert captured["headers"]["Host"] == "hooks.example.test:8443"
    assert captured["path"] == "/run?q=1"
    assert captured["released"] is True
    assert captured["closed"] is True


def test_redirects_are_revalidated_for_every_target(monkeypatch):
    calls = []
    responses = [
        (302, {"Location": "https://second.example.test/hook"}, b""),
        (200, {}, b"ok"),
    ]

    def fake_request_once(url, **kwargs):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(
        "app.services.orchestration.webhooks._request_once",
        fake_request_once,
    )

    response = deliver_webhook(
        url="https://first.example.test/hook",
        method="POST",
        headers={},
        body=b"{}",
        timeout_seconds=5,
        private_network_policy="deny",
    )

    assert calls == [
        "https://first.example.test/hook",
        "https://second.example.test/hook",
    ]
    assert response.status == 200
    assert response.redirects == 1


def test_worker_marks_success_and_never_logs_secret_response(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    action = create_webhook_action(
        group_id=group.id,
        name="success",
        url="https://example.test/hook",
        headers={"Authorization": "Bearer top-secret"},
    )
    _publish(group, action.id)
    upsert_alert(_event(route, "worker-success"))

    monkeypatch.setattr(
        "app.services.orchestration.webhooks.deliver_webhook",
        lambda **kwargs: WebhookResponse(
            status=204,
            body=b'access_token=must-not-be-stored',
            final_url=kwargs["url"],
            redirects=0,
        ),
    )

    result = process_due_webhooks(now=utc_now())

    row = AutomationExecution.get()
    assert result["succeeded"] == 1
    assert row.status == "succeeded"
    assert row.response_status == 204
    assert "must-not-be-stored" not in (row.response_excerpt_safe or "")
    assert "***REDACTED***" in row.response_excerpt_safe


def test_worker_uses_queued_request_snapshot_after_action_edit(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    action = create_webhook_action(
        group_id=group.id,
        name="snapshot",
        url="https://original.example.test/hook",
        retry_count=0,
    )
    _publish(group, action.id)
    upsert_alert(_event(route, "worker-snapshot"))

    action.url = "https://edited.example.test/hook"
    action.method = "PUT"
    action.timeout_seconds = 30
    action.save()
    captured = {}

    def succeed(**kwargs):
        captured.update(kwargs)
        return WebhookResponse(
            status=200,
            body=b"ok",
            final_url=kwargs["url"],
            redirects=0,
        )

    monkeypatch.setattr(
        "app.services.orchestration.webhooks.deliver_webhook",
        succeed,
    )

    process_due_webhooks(now=utc_now())

    assert captured["url"] == "https://original.example.test/hook"
    assert captured["method"] == "POST"
    assert captured["timeout_seconds"] == 10


def test_worker_retries_then_marks_terminal_failure(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    action = create_webhook_action(
        group_id=group.id,
        name="retry",
        url="https://example.test/hook",
        retry_count=1,
    )
    _publish(group, action.id)
    upsert_alert(_event(route, "worker-retry"))

    def fail(**kwargs):
        raise WebhookDeliveryError("temporary failure", status=503)

    monkeypatch.setattr("app.services.orchestration.webhooks.deliver_webhook", fail)

    first = process_due_webhooks(now=utc_now())
    row = AutomationExecution.get()
    assert first["failed"] == 1
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.next_attempt_at is not None

    retry_at = row.next_attempt_at + timedelta(seconds=1)
    second = process_due_webhooks(now=retry_at)
    row = AutomationExecution.get_by_id(row.id)
    assert second["failed"] == 1
    assert row.status == "failed"
    assert row.attempts == 2
    assert row.finished_at is not None
