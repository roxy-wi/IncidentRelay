"""Bounded JSON reads using the existing DNS-pinned outbound HTTP transport."""

import json
import re
import time
from urllib.parse import quote, urlencode

from app.services.directory_sync.config import SyncError, path_value
from app.services.orchestration.webhooks import (
    WebhookDeliveryError, WebhookSecurityError, WebhookValidationError, _request_once,
)

_VARIABLE = re.compile(r"\{([a-z_]+)\}")


def render(value, context, *, url=False):
    """Substitute known variables; whole-value variables preserve JSON types."""
    if isinstance(value, dict):
        return {key: render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, context) for item in value]
    if not isinstance(value, str):
        return value

    def lookup(name):
        if name not in context:
            raise SyncError(f"Unknown request variable: {name}")
        return context[name]

    match = _VARIABLE.fullmatch(value)
    if match and not url:
        return lookup(match.group(1))
    return _VARIABLE.sub(
        lambda match: quote(str(lookup(match.group(1))), safe="") if url
        else str(lookup(match.group(1))), value,
    )


class ApiClient:
    """Read complete datasets; reject redirects, malformed pages and truncation."""

    def __init__(self, config, headers, heartbeat=lambda: None):
        self.config = config
        self.headers = headers
        self.heartbeat = heartbeat
        self.deadline = time.monotonic() + 1800
        self.requests = 0
        self.samples = {}

    def request(self, name, context, page_params=None):
        op = self.config.operations[name]
        path = render(op.path, context, url=True)
        params = render(op.params, context)
        params.update(page_params or {})
        url = self.config.base_url + path
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        body = render(op.body, context)
        for attempt in range(3):
            if time.monotonic() >= self.deadline or self.requests >= 10000:
                raise SyncError("API request budget exceeded; reduce the selected dataset")
            self.heartbeat()
            self.requests += 1
            try:
                status, _, payload = _request_once(
                    url, method=op.method, headers={"Accept": "application/json", "Content-Type": "application/json", **self.headers},
                    body=json.dumps(body).encode() if body is not None else b"",
                    timeout_seconds=self.config.timeout_seconds,
                    private_network_policy=self.config.private_network_policy,
                    max_response_bytes=8 * 1024 * 1024,
                )
            except (WebhookSecurityError, WebhookValidationError) as error:
                raise SyncError("API target blocked; check HTTPS and the server network allowlist") from error
            except WebhookDeliveryError as error:
                if attempt < 2 and error.retryable:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                raise SyncError(f"{name}: API connection failed") from error
            if status in {408, 429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(0.25 * (2 ** attempt))
                continue
            if not 200 <= status < 300:
                raise SyncError(f"{name}: API returned HTTP {status}")
            try:
                data = json.loads(payload)
            except (ValueError, UnicodeError) as error:
                raise SyncError(f"{name}: API did not return valid JSON") from error
            if not isinstance(data, (dict, list)):
                raise SyncError(f"{name}: expected a JSON object or array")
            # Show field names/types only: no raw profiles, tokens or response bodies.
            self.samples.setdefault(name, describe(data))
            return data
        raise SyncError(f"{name}: retries exhausted")

    def records(self, name, context):
        op = self.config.operations[name]
        pagination = op.pagination
        result, seen = [], set()
        cursor = pagination.start
        for page in range(pagination.max_pages):
            params = {}
            if pagination.mode != "none":
                params[pagination.size_parameter] = pagination.size
                if pagination.mode != "cursor" or page:
                    params[pagination.parameter] = cursor
            data = self.request(name, context, params)
            records = path_value(data, op.items)
            if not isinstance(records, list):
                raise SyncError(f"{name}: items mapping must resolve to an array")
            if not all(isinstance(item, dict) for item in records):
                raise SyncError(f"{name}: records must be JSON objects")
            result.extend(records)
            if len(result) > 100000:
                raise SyncError(f"{name}: dataset exceeds 100000 records")
            if pagination.mode == "none":
                return result
            if pagination.mode == "cursor":
                cursor = path_value(data, pagination.next_path)
                if cursor in (None, ""):
                    return result
                if not isinstance(cursor, (str, int)) or str(cursor) in seen:
                    raise SyncError(f"{name}: repeated or invalid pagination cursor")
                seen.add(str(cursor))
            else:
                if len(records) < pagination.size:
                    return result
                cursor += pagination.size if pagination.mode == "offset" else 1
        raise SyncError(f"{name}: pagination limit reached; no changes were applied")


def describe(value, depth=0):
    """Provide a bounded schema sample for mapping without exposing API values."""
    if depth > 8:
        return "…"
    if isinstance(value, dict):
        return {str(key): describe(item, depth + 1) for key, item in list(value.items())[:80]}
    if isinstance(value, list):
        return [describe(value[0], depth + 1)] if value else []
    return type(value).__name__
