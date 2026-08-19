"""Asynchronous, audited and SSRF-resistant Event Orchestration webhooks."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import logging
import socket
import ssl
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

import urllib3
from peewee import fn

from app.modules.common import utc_now
from app.modules.crypto import decrypt_json, decrypt_secret, encrypt_json, encrypt_secret
from app.modules.db.models import (
    AutomationExecution,
    OrchestrationExecution,
    OrchestrationWebhookAction,
)
from app.modules.redaction import redact_secrets
from app.services.orchestration.templates import render_template, validate_template
from app.settings import Config

logger = logging.getLogger("oncall.orchestration.webhooks")

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({408, 409, 425, 429})
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


class WebhookValidationError(ValueError):
    pass


class WebhookSecurityError(RuntimeError):
    pass


class WebhookDeliveryError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None):
        self.retryable = bool(retryable)
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class WebhookResponse:
    status: int
    body: bytes
    final_url: str
    redirects: int


def _safe_error(value: Any, *, limit: int = 2048) -> str:
    text = str(redact_secrets(value))
    return text if len(text) <= limit else text[:limit] + "…"


def _validate_url_syntax(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise WebhookValidationError("webhook URL must use http or https")
    if parsed.username or parsed.password:
        raise WebhookValidationError("webhook URL must not contain credentials")
    if not parsed.hostname:
        raise WebhookValidationError("webhook URL requires a hostname")
    if parsed.fragment:
        raise WebhookValidationError("webhook URL must not contain a fragment")
    if redact_secrets(value) != value:
        raise WebhookValidationError(
            "webhook URL must not contain secret query parameters; use encrypted headers"
        )
    if parsed.scheme.lower() == "http" and not bool(
        getattr(Config, "ORCHESTRATION_WEBHOOK_ALLOW_HTTP", False)
    ):
        raise WebhookValidationError("webhook URL must use HTTPS")
    return value


def _normalize_headers(headers: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for raw_name, raw_value in dict(headers or {}).items():
        name = str(raw_name or "").strip()
        if not name or any(ch in name for ch in "\r\n:"):
            raise WebhookValidationError("invalid webhook header name")
        if name.lower() in _HOP_BY_HOP_HEADERS:
            raise WebhookValidationError(f"webhook header {name!r} is not allowed")
        value = str(raw_value if raw_value is not None else "")
        if "\r" in value or "\n" in value:
            raise WebhookValidationError("webhook header values must not contain newlines")
        if "{{" in value or "}}" in value:
            issues = validate_template(value, path=f"headers.{name}")
            if issues:
                raise WebhookValidationError(issues[0].message)
        result[name] = value
    return result


def create_webhook_action(
    *,
    group_id: int,
    name: str,
    url: str,
    method: str = "POST",
    headers: Optional[Mapping[str, Any]] = None,
    body_template: Optional[str] = None,
    description: Optional[str] = None,
    timeout_seconds: int = 10,
    retry_count: int = 2,
    private_network_policy: str = "deny",
    enabled: bool = True,
    actor_id: Optional[int] = None,
) -> OrchestrationWebhookAction:
    """Create one encrypted group-owned webhook action."""
    name = str(name or "").strip()
    if not name:
        raise WebhookValidationError("webhook action name is required")
    method = str(method or "POST").upper()
    if method not in _ALLOWED_METHODS:
        raise WebhookValidationError("unsupported webhook method")
    url = _validate_url_syntax(url)
    headers = _normalize_headers(headers)
    if body_template is not None:
        body_template = str(body_template)
        issues = validate_template(body_template, path="body_template")
        if issues:
            raise WebhookValidationError(issues[0].message)
    return OrchestrationWebhookAction.create(
        group=group_id,
        name=name,
        description=description,
        url=url,
        method=method,
        headers_encrypted=encrypt_json(headers) if headers else None,
        body_template=body_template,
        timeout_seconds=int(timeout_seconds),
        retry_count=int(retry_count),
        private_network_policy=private_network_policy,
        enabled=bool(enabled),
        created_by=actor_id,
    )


def update_webhook_action(action_id: int, **changes) -> OrchestrationWebhookAction:
    """Update a webhook action while preserving encrypted headers when omitted."""
    action = OrchestrationWebhookAction.get_by_id(action_id)
    if "name" in changes:
        action.name = str(changes["name"] or "").strip()
        if not action.name:
            raise WebhookValidationError("webhook action name is required")
    if "url" in changes:
        action.url = _validate_url_syntax(changes["url"])
    if "method" in changes:
        method = str(changes["method"] or "POST").upper()
        if method not in _ALLOWED_METHODS:
            raise WebhookValidationError("unsupported webhook method")
        action.method = method
    if "headers" in changes:
        normalized_headers = _normalize_headers(changes["headers"])
        action.headers_encrypted = (
            encrypt_json(normalized_headers) if normalized_headers else None
        )
    if "body_template" in changes:
        template = changes["body_template"]
        if template is not None:
            template = str(template)
            issues = validate_template(template, path="body_template")
            if issues:
                raise WebhookValidationError(issues[0].message)
        action.body_template = template
    for field_name in (
        "description",
        "timeout_seconds",
        "retry_count",
        "private_network_policy",
        "enabled",
    ):
        if field_name in changes:
            setattr(action, field_name, changes[field_name])
    action.save()
    return action


def serialize_webhook_action(action: OrchestrationWebhookAction) -> Dict[str, Any]:
    """Return safe metadata without decrypting secret headers."""
    return {
        "id": action.id,
        "uid": str(action.uid),
        "group_id": action.group_id,
        "name": action.name,
        "description": action.description,
        "url": redact_secrets(action.url),
        "method": action.method,
        "has_headers": bool(action.headers_encrypted),
        "body_template": action.body_template,
        "timeout_seconds": action.timeout_seconds,
        "retry_count": action.retry_count,
        "private_network_policy": action.private_network_policy,
        "enabled": bool(action.enabled),
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def _iter_webhook_requests(rules: Iterable[Mapping[str, Any]]):
    for rule in rules or ():
        path = rule.get("path")
        for step in rule.get("actions") or ():
            if not step.get("success") or step.get("type") != "enqueue_webhook":
                continue
            after = step.get("after") or {}
            action_id = after.get("action_id") if isinstance(after, Mapping) else None
            if action_id:
                yield int(action_id), str(path or "")
        yield from _iter_webhook_requests(rule.get("children") or ())


def _render_headers(headers: Mapping[str, str], context: Mapping[str, Any]) -> Dict[str, str]:
    rendered: Dict[str, str] = {}
    for name, value in headers.items():
        if "{{" in value or "}}" in value:
            value = render_template(value, context).value
        if "\r" in value or "\n" in value:
            raise WebhookValidationError("rendered webhook header contains a newline")
        rendered[name] = value
    return rendered


def _render_body(action: OrchestrationWebhookAction, context: Mapping[str, Any]) -> str:
    if action.body_template is not None:
        return render_template(action.body_template, context).value
    return json.dumps(
        {
            "event": copy.deepcopy(context.get("event") or {}),
            "result": copy.deepcopy(context.get("result") or {}),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def enqueue_execution_webhooks(
    orchestration_execution_id: int,
    *,
    alert_group_id: Optional[int] = None,
) -> int:
    """Materialize requested webhooks from an applied execution exactly once."""
    execution = OrchestrationExecution.get_by_id(orchestration_execution_id)
    trace = execution.trace_json or {}
    if not bool(trace.get("applied")):
        return 0
    result = trace.get("result") or {}
    context = result.get("context") or {}
    queued = 0
    for ordinal, (action_id, rule_path) in enumerate(
        _iter_webhook_requests(result.get("rules") or ())
    ):
        action = OrchestrationWebhookAction.get_or_none(
            (OrchestrationWebhookAction.id == action_id)
            & (OrchestrationWebhookAction.group == execution.group_id)
            & (OrchestrationWebhookAction.enabled == True)  # noqa: E712
            & (OrchestrationWebhookAction.deleted == False)  # noqa: E712
            & OrchestrationWebhookAction.deleted_at.is_null(True)
        )
        if action is None:
            logger.warning(
                "orchestration webhook action skipped",
                extra={"extra": {
                    "execution_id": execution.id,
                    "action_id": action_id,
                    "reason": "missing_or_disabled",
                }},
            )
            continue
        headers = _render_headers(
            decrypt_json(action.headers_encrypted, default={}) or {},
            context,
        )
        body = _render_body(action, context)
        key_material = f"{execution.uid}:{action.uid}:{rule_path}:{ordinal}"
        idempotency_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        headers.setdefault("Idempotency-Key", idempotency_key)
        headers.setdefault("User-Agent", "IncidentRelay-Orchestration/1")
        if body and not any(name.lower() == "content-type" for name in headers):
            headers["Content-Type"] = "application/json"
        metadata = {
            "url": action.url,
            "method": action.method,
            "timeout_seconds": int(action.timeout_seconds),
            "retry_count": int(action.retry_count),
            "private_network_policy": action.private_network_policy,
            "header_names": sorted(headers),
            "body_bytes": len(body.encode("utf-8")),
        }
        row, created = AutomationExecution.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "action": action.id,
                "orchestration_execution": execution.id,
                "group": execution.group_id,
                "alert_group_id": alert_group_id,
                "rule_path": rule_path,
                "status": "pending",
                "request_metadata_json": metadata,
                "request_headers_encrypted": encrypt_json(headers),
                "request_body_encrypted": encrypt_secret(body),
                "next_attempt_at": utc_now(),
            },
        )
        if not created and alert_group_id and row.alert_group_id is None:
            row.alert_group_id = alert_group_id
            row.save(only=[AutomationExecution.alert_group_id])
        queued += int(created)
    return queued


def _allowlist_networks() -> Sequence[Any]:
    raw = str(
        getattr(Config, "ORCHESTRATION_WEBHOOK_PRIVATE_NETWORK_ALLOWLIST", "") or ""
    )
    result = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise WebhookSecurityError("invalid private network allowlist") from exc
    return tuple(result)


def _ip_allowed(address: ipaddress._BaseAddress, policy: str) -> bool:
    unsafe = (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
    if not unsafe:
        return True
    if policy != "allowlist":
        return False
    return any(address in network for network in _allowlist_networks())


def resolve_webhook_target(url: str, *, private_network_policy: str = "deny"):
    """Resolve and validate every address, then return one pinned target IP."""
    url = _validate_url_syntax(url)
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        literal = ipaddress.ip_address(parsed.hostname)
        addresses = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise WebhookDeliveryError("webhook DNS resolution failed") from exc
        addresses = []
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
    if not addresses:
        raise WebhookDeliveryError("webhook hostname resolved to no addresses")
    if not all(_ip_allowed(address, private_network_policy) for address in addresses):
        raise WebhookSecurityError("webhook target resolves to a blocked network")
    return parsed, str(addresses[0]), port


def _host_header(parsed) -> str:
    host = parsed.hostname or ""
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    return f"{host}:{parsed.port}" if parsed.port and parsed.port != default_port else host


def _request_once(
    url: str,
    *,
    method: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: int,
    private_network_policy: str,
) -> Tuple[int, Mapping[str, str], bytes]:
    parsed, target_ip, port = resolve_webhook_target(
        url,
        private_network_policy=private_network_policy,
    )
    request_headers = dict(headers)
    request_headers["Host"] = _host_header(parsed)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    timeout = urllib3.Timeout(connect=timeout_seconds, read=timeout_seconds)
    if parsed.scheme.lower() == "https":
        pool = urllib3.HTTPSConnectionPool(
            target_ip,
            port=port,
            timeout=timeout,
            maxsize=1,
            block=True,
            retries=False,
            cert_reqs=ssl.CERT_REQUIRED,
            assert_hostname=parsed.hostname,
            server_hostname=parsed.hostname,
        )
    else:
        pool = urllib3.HTTPConnectionPool(
            target_ip,
            port=port,
            timeout=timeout,
            maxsize=1,
            block=True,
            retries=False,
        )
    response = None
    try:
        response = pool.urlopen(
            method,
            path,
            body=body or None,
            headers=request_headers,
            redirect=False,
            retries=False,
            preload_content=False,
        )
        limit = int(getattr(Config, "ORCHESTRATION_WEBHOOK_MAX_RESPONSE_BYTES", 65536))
        payload = response.read(amt=limit + 1, decode_content=True)
        if len(payload) > limit:
            raise WebhookDeliveryError(
                "webhook response exceeded the configured size limit",
                retryable=False,
                status=int(response.status),
            )
        return int(response.status), dict(response.headers), payload
    except WebhookDeliveryError:
        raise
    except Exception as exc:
        raise WebhookDeliveryError(f"webhook request failed: {exc.__class__.__name__}") from exc
    finally:
        if response is not None:
            response.release_conn()
        pool.close()


def deliver_webhook(
    *,
    url: str,
    method: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: int,
    private_network_policy: str,
) -> WebhookResponse:
    """Deliver one request with pinned DNS and bounded redirects."""
    current_url = url
    current_method = method
    current_body = body
    max_redirects = int(getattr(Config, "ORCHESTRATION_WEBHOOK_MAX_REDIRECTS", 3))
    for redirects in range(max_redirects + 1):
        status, response_headers, payload = _request_once(
            current_url,
            method=current_method,
            headers=headers,
            body=current_body,
            timeout_seconds=timeout_seconds,
            private_network_policy=private_network_policy,
        )
        if status not in _REDIRECT_STATUSES:
            return WebhookResponse(status, payload, current_url, redirects)
        location = response_headers.get("Location") or response_headers.get("location")
        if not location:
            return WebhookResponse(status, payload, current_url, redirects)
        if redirects >= max_redirects:
            raise WebhookDeliveryError("webhook redirect limit exceeded", retryable=False)
        current_url = urljoin(current_url, location)
        _validate_url_syntax(current_url)
        if status == 303:
            current_method = "GET"
            current_body = b""
    raise WebhookDeliveryError("webhook redirect limit exceeded", retryable=False)


def _requeue_stale_claims(now) -> int:
    cutoff = now - timedelta(
        seconds=int(getattr(Config, "ORCHESTRATION_WEBHOOK_CLAIM_TTL_SECONDS", 300))
    )
    return (
        AutomationExecution.update(
            status="pending",
            claim_token=None,
            claimed_at=None,
            next_attempt_at=now,
        )
        .where(
            (AutomationExecution.status == "running")
            & (AutomationExecution.claimed_at <= cutoff)
        )
        .execute()
    )


def _group_capacity(group_id: int, *, now) -> bool:
    concurrency = int(
        getattr(Config, "ORCHESTRATION_WEBHOOK_PER_GROUP_CONCURRENCY", 2)
    )
    running = (
        AutomationExecution.select(fn.COUNT(AutomationExecution.id))
        .where(
            (AutomationExecution.group == group_id)
            & (AutomationExecution.status == "running")
        )
        .scalar()
        or 0
    )
    if concurrency > 0 and int(running) >= concurrency:
        return False
    rate = int(
        getattr(Config, "ORCHESTRATION_WEBHOOK_PER_GROUP_RATE_PER_MINUTE", 60)
    )
    if rate <= 0:
        return True
    since = now - timedelta(minutes=1)
    recent = (
        AutomationExecution.select(fn.COUNT(AutomationExecution.id))
        .where(
            (AutomationExecution.group == group_id)
            & AutomationExecution.started_at.is_null(False)
            & (AutomationExecution.started_at >= since)
        )
        .scalar()
        or 0
    )
    return int(recent) < rate


def _claim_one(execution_id: int, *, now) -> Optional[AutomationExecution]:
    token = uuid.uuid4().hex
    row = AutomationExecution.get_or_none(AutomationExecution.id == execution_id)
    if row is None or not _group_capacity(row.group_id, now=now):
        return None
    updated = (
        AutomationExecution.update(
            status="running",
            claim_token=token,
            claimed_at=now,
            started_at=now,
            attempts=AutomationExecution.attempts + 1,
            error_safe=None,
        )
        .where(
            (AutomationExecution.id == execution_id)
            & (AutomationExecution.status == "pending")
            & (
                AutomationExecution.next_attempt_at.is_null(True)
                | (AutomationExecution.next_attempt_at <= now)
            )
        )
        .execute()
    )
    if updated != 1:
        return None
    return AutomationExecution.get(
        (AutomationExecution.id == execution_id)
        & (AutomationExecution.claim_token == token)
    )


def _mark_succeeded(row: AutomationExecution, response: WebhookResponse, *, now):
    excerpt = response.body.decode("utf-8", errors="replace")
    excerpt = _safe_error(excerpt, limit=4096)
    AutomationExecution.update(
        status="succeeded",
        response_status=response.status,
        response_excerpt_safe=excerpt,
        error_safe=None,
        claim_token=None,
        claimed_at=None,
        next_attempt_at=None,
        finished_at=now,
    ).where(
        (AutomationExecution.id == row.id)
        & (AutomationExecution.status == "running")
        & (AutomationExecution.claim_token == row.claim_token)
    ).execute()


def _mark_failed(row: AutomationExecution, exc: Exception, *, now):
    metadata = row.request_metadata_json or {}
    attempts = int(row.attempts or 0)
    max_attempts = 1 + int(metadata.get("retry_count", row.action.retry_count) or 0)
    retryable = bool(getattr(exc, "retryable", True))
    status_code = getattr(exc, "status", None)
    if retryable and attempts < max_attempts:
        status = "pending"
        base = int(getattr(Config, "ORCHESTRATION_WEBHOOK_RETRY_BASE_SECONDS", 30))
        next_attempt_at = now + timedelta(
            seconds=min(base * (2 ** max(attempts - 1, 0)), 3600)
        )
        finished_at = None
    else:
        status = "failed"
        next_attempt_at = None
        finished_at = now
    AutomationExecution.update(
        status=status,
        response_status=status_code,
        error_safe=_safe_error(exc),
        claim_token=None,
        claimed_at=None,
        next_attempt_at=next_attempt_at,
        finished_at=finished_at,
    ).where(
        (AutomationExecution.id == row.id)
        & (AutomationExecution.status == "running")
        & (AutomationExecution.claim_token == row.claim_token)
    ).execute()


def _deliver_claimed(row: AutomationExecution, *, now):
    action = row.action
    if not action.enabled or action.deleted or action.deleted_at is not None:
        AutomationExecution.update(
            status="cancelled",
            error_safe="webhook action is disabled",
            claim_token=None,
            claimed_at=None,
            finished_at=now,
        ).where(
            (AutomationExecution.id == row.id)
            & (AutomationExecution.claim_token == row.claim_token)
        ).execute()
        return "cancelled"
    headers = decrypt_json(row.request_headers_encrypted, default={}) or {}
    body = (decrypt_secret(row.request_body_encrypted) or "").encode("utf-8")
    metadata = row.request_metadata_json or {}
    response = deliver_webhook(
        url=metadata.get("url") or action.url,
        method=metadata.get("method") or action.method,
        headers=headers,
        body=body,
        timeout_seconds=int(
            metadata.get("timeout_seconds", action.timeout_seconds)
        ),
        private_network_policy=(
            metadata.get("private_network_policy")
            or action.private_network_policy
        ),
    )
    if 200 <= response.status < 300:
        _mark_succeeded(row, response, now=now)
        return "succeeded"
    retryable = response.status in _RETRYABLE_STATUSES or response.status >= 500
    raise WebhookDeliveryError(
        f"webhook returned HTTP {response.status}",
        retryable=retryable,
        status=response.status,
    )


def process_due_webhooks(limit=50, *, now=None) -> Dict[str, int]:
    """Claim and deliver queued webhook actions with bounded retries."""
    now = now or utc_now()
    result = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
        "requeued": _requeue_stale_claims(now),
    }
    rows = list(
        AutomationExecution.select(AutomationExecution.id)
        .where(
            (AutomationExecution.status == "pending")
            & (
                AutomationExecution.next_attempt_at.is_null(True)
                | (AutomationExecution.next_attempt_at <= now)
            )
        )
        .order_by(AutomationExecution.created_at.asc(), AutomationExecution.id.asc())
        .limit(int(limit))
    )
    for candidate in rows:
        claimed = _claim_one(candidate.id, now=now)
        if claimed is None:
            continue
        result["processed"] += 1
        try:
            outcome = _deliver_claimed(claimed, now=utc_now())
            result[outcome] += 1
        except Exception as exc:
            logger.warning(
                "orchestration webhook execution failed",
                extra={"extra": {
                    "automation_execution_id": claimed.id,
                    "action_id": claimed.action_id,
                    "error": _safe_error(exc),
                }},
            )
            _mark_failed(claimed, exc, now=utc_now())
            result["failed"] += 1
    return result


def retry_failed_webhook(execution_id: int, *, now=None) -> bool:
    now = now or utc_now()
    updated = (
        AutomationExecution.update(
            status="pending",
            attempts=0,
            response_status=None,
            response_excerpt_safe=None,
            error_safe=None,
            next_attempt_at=now,
            claim_token=None,
            claimed_at=None,
            started_at=None,
            finished_at=None,
        )
        .where(
            (AutomationExecution.id == execution_id)
            & (AutomationExecution.status == "failed")
        )
        .execute()
    )
    return updated == 1


def cleanup_webhook_executions(*, now=None) -> int:
    now = now or utc_now()
    cutoff = now - timedelta(
        days=int(getattr(Config, "ORCHESTRATION_WEBHOOK_EXECUTION_RETENTION_DAYS", 30))
    )
    return (
        AutomationExecution.delete()
        .where(
            AutomationExecution.status.in_(tuple(_TERMINAL_STATUSES))
            & (AutomationExecution.finished_at <= cutoff)
        )
        .execute()
    )


__all__ = [
    "WebhookDeliveryError",
    "WebhookResponse",
    "WebhookSecurityError",
    "WebhookValidationError",
    "cleanup_webhook_executions",
    "create_webhook_action",
    "deliver_webhook",
    "enqueue_execution_webhooks",
    "process_due_webhooks",
    "resolve_webhook_target",
    "retry_failed_webhook",
    "serialize_webhook_action",
    "update_webhook_action",
]
