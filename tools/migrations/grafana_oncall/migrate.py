#!/usr/bin/env python3
"""Migrate Grafana OnCall OSS configuration to IncidentRelay through HTTP APIs.

The command is intentionally dry-run by default. It never reads either
application database directly and never prints credentials or generated intake
tokens to the terminal/report. Secrets are written only to a chmod-0600 JSON
file when --apply creates IncidentRelay routes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


STATE_VERSION = 1
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 4
SUPPORTED_IR_SOURCES = {
    "alertmanager",
    "grafana",
    "webhook",
    "zabbix",
    "sentry",
    "librenms",
    "rmon",
}
WEEKDAY_MAP = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}


class MigrationError(RuntimeError):
    """Raised when migration cannot continue safely."""


class ApiError(MigrationError):
    """HTTP API failure with structured response details."""

    def __init__(
        self,
        method: str,
        url: str,
        status: int | None,
        message: str,
        payload: Any = None,
    ) -> None:
        super().__init__(f"{method} {url}: {status or 'network'}: {message}")
        self.method = method
        self.url = url
        self.status = status
        self.payload = payload


@dataclass(slots=True)
class Event:
    level: str
    entity: str
    action: str
    message: str
    source_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class Reporter:
    """Collect migration actions and warnings without storing secrets."""

    def __init__(self, strict: bool = False) -> None:
        self.strict = strict
        self.events: list[Event] = []

    def add(
        self,
        level: str,
        entity: str,
        action: str,
        message: str,
        source_id: Any = None,
        **details: Any,
    ) -> None:
        event = Event(
            level=level,
            entity=entity,
            action=action,
            message=message,
            source_id=str(source_id) if source_id is not None else None,
            details={key: value for key, value in details.items() if value is not None},
        )
        self.events.append(event)
        prefix = level.upper().ljust(7)
        source = f" [{event.source_id}]" if event.source_id else ""
        print(f"{prefix} {entity}{source}: {message}")
        if self.strict and level == "warning":
            raise MigrationError(f"strict mode: {entity}: {message}")

    def summary(self) -> dict[str, Any]:
        by_level = Counter(item.level for item in self.events)
        by_entity_action = Counter(
            f"{item.entity}:{item.action}" for item in self.events
        )
        return {
            "events": len(self.events),
            "levels": dict(sorted(by_level.items())),
            "actions": dict(sorted(by_entity_action.items())),
        }

    def write(self, output_dir: Path, metadata: Mapping[str, Any]) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": dict(metadata),
            "summary": self.summary(),
            "events": [
                {
                    "level": event.level,
                    "entity": event.entity,
                    "action": event.action,
                    "message": event.message,
                    "source_id": event.source_id,
                    "details": event.details,
                }
                for event in self.events
            ],
        }
        write_json(output_dir / "report.json", payload)
        if metadata.get("mode") == "dry-run":
            write_json(output_dir / "plan.json", payload)

        lines = [
            "# Grafana OnCall → IncidentRelay migration report",
            "",
            f"- Mode: **{metadata.get('mode')}**",
            f"- Generated: `{metadata.get('generated_at')}`",
            f"- Grafana OnCall: `{metadata.get('oncall_url')}`",
            f"- IncidentRelay: `{metadata.get('ir_url')}`",
            "",
            "## Summary",
            "",
        ]
        for key, value in sorted(self.summary()["levels"].items()):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Events", ""])
        for event in self.events:
            source = f" `{event.source_id}`" if event.source_id else ""
            lines.append(
                f"- **{event.level.upper()}** `{event.entity}`{source} "
                f"— {event.message}"
            )
            for key, value in event.details.items():
                lines.append(f"  - {key}: `{json_scalar(value)}`")
        (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class JsonHttpClient:
    """Minimal JSON HTTP client with retries and TLS verification."""

    def __init__(
        self,
        base_url: str,
        headers: Mapping[str, str],
        *,
        verify_tls: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.headers = dict(headers)
        self.timeout = timeout
        self.retries = retries
        self.ssl_context = ssl.create_default_context()
        if not verify_tls:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | list[Any] | None = None,
        expected: Iterable[int] = (200,),
    ) -> Any:
        url = (
            path_or_url
            if path_or_url.startswith(("http://", "https://"))
            else urljoin(self.base_url, path_or_url.lstrip("/"))
        )
        if query:
            filtered = {
                key: value
                for key, value in query.items()
                if value is not None and value != ""
            }
            if filtered:
                url += ("&" if "?" in url else "?") + urlencode(filtered, doseq=True)

        data = None
        headers = {"Accept": "application/json", **self.headers}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            request = Request(url, data=data, headers=headers, method=method)
            try:
                with urlopen(
                    request,
                    timeout=self.timeout,
                    context=self.ssl_context,
                ) as response:
                    raw = response.read()
                    status = response.status
                    if status not in expected:
                        raise ApiError(method, url, status, "unexpected status")
                    if not raw:
                        return None
                    content_type = response.headers.get("Content-Type", "")
                    if "json" in content_type or raw[:1] in (b"{", b"["):
                        return json.loads(raw.decode("utf-8"))
                    return raw.decode("utf-8", errors="replace")
            except HTTPError as exc:
                raw = exc.read()
                payload: Any = None
                message = exc.reason or "HTTP error"
                if raw:
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                        message = (
                            payload.get("message")
                            or payload.get("error")
                            or message
                        ) if isinstance(payload, dict) else message
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        message = raw.decode("utf-8", errors="replace")[:500]
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ApiError(method, url, exc.code, str(message), payload) from exc
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ApiError(method, url, None, str(exc)) from exc

        raise ApiError(method, url, None, str(last_error or "request failed"))

    def get(self, path: str, query: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, query=query, expected=(200,))

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self.request("POST", path, body=body, expected=(200, 201))

    def put(self, path: str, body: Mapping[str, Any]) -> Any:
        return self.request("PUT", path, body=body, expected=(200, 201))


class GrafanaOnCallClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        grafana_url: str | None = None,
        verify_tls: bool = True,
    ) -> None:
        headers = {"Authorization": token}
        if grafana_url:
            headers["X-Grafana-URL"] = grafana_url
        self.http = JsonHttpClient(base_url, headers, verify_tls=verify_tls)

    def list_all(
        self,
        path: str,
        query: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = path
        next_query = query
        seen: set[str] = set()
        while next_url:
            marker = f"{next_url}|{next_query}"
            if marker in seen:
                raise MigrationError(f"pagination loop detected for {path}")
            seen.add(marker)
            payload = self.http.get(next_url, query=next_query)
            next_query = None
            if isinstance(payload, list):
                items.extend(item for item in payload if isinstance(item, dict))
                break
            if not isinstance(payload, dict):
                raise MigrationError(f"unexpected list response for {path}")
            results = payload.get("results")
            if isinstance(results, list):
                items.extend(item for item in results if isinstance(item, dict))
            else:
                # Some older endpoints return a plain object for a list call.
                items.append(payload)
                break
            next_url = payload.get("next")
        return items

    def snapshot(self, reporter: Reporter) -> dict[str, Any]:
        endpoints = {
            "users": "/api/v1/users/",
            "teams": "/api/v1/teams/",
            "schedules": "/api/v1/schedules/",
            "on_call_shifts": "/api/v1/on_call_shifts/",
            "escalation_chains": "/api/v1/escalation_chains/",
            "escalation_policies": "/api/v1/escalation_policies/",
            "integrations": "/api/v1/integrations/",
            "routes": "/api/v1/routes/",
        }
        snapshot: dict[str, Any] = {}
        for name, path in endpoints.items():
            snapshot[name] = self.list_all(path)
            reporter.add(
                "info",
                "snapshot",
                "downloaded",
                f"Downloaded {len(snapshot[name])} {name}",
            )
        try:
            snapshot["outgoing_webhooks"] = self.list_all(
                "/api/v1/outgoing_webhooks/"
            )
        except ApiError as exc:
            if exc.status in {403, 404}:
                snapshot["outgoing_webhooks"] = []
                reporter.add(
                    "warning",
                    "snapshot",
                    "skipped",
                    "Outgoing webhooks endpoint is unavailable; secrets cannot be migrated anyway",
                    status=exc.status,
                )
            else:
                raise
        return snapshot


class IncidentRelayClient:
    def __init__(self, base_url: str, token: str, *, verify_tls: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = JsonHttpClient(
            self.base_url,
            {"Authorization": f"Bearer {token}"},
            verify_tls=verify_tls,
        )

    def get(self, path: str, query: Mapping[str, Any] | None = None) -> Any:
        return self.http.get(path, query=query)

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self.http.post(path, body)

    def put(self, path: str, body: Mapping[str, Any]) -> Any:
        return self.http.put(path, body)


class StateStore:
    def __init__(self, path: Path, oncall_url: str, ir_url: str) -> None:
        self.path = path
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") != STATE_VERSION:
                raise MigrationError("unsupported migration state version")
            stored_source = str((payload.get("source") or {}).get("oncall_url") or "").rstrip("/")
            stored_target = str((payload.get("target") or {}).get("ir_url") or "").rstrip("/")
            if stored_source and stored_source != oncall_url.rstrip("/"):
                raise MigrationError("state file belongs to a different Grafana OnCall instance")
            if stored_target and stored_target != ir_url.rstrip("/"):
                raise MigrationError("state file belongs to a different IncidentRelay instance")
            self.data = payload
        else:
            self.data = {
                "version": STATE_VERSION,
                "source": {"oncall_url": oncall_url.rstrip("/")},
                "target": {"ir_url": ir_url.rstrip("/")},
                "mappings": {},
            }

    def mapping(self, category: str) -> dict[str, int]:
        mappings = self.data.setdefault("mappings", {})
        return mappings.setdefault(category, {})

    def get(self, category: str, source_key: Any) -> int | None:
        value = self.mapping(category).get(str(source_key))
        return int(value) if value is not None else None

    def set(self, category: str, source_key: Any, target_id: int) -> None:
        self.mapping(category)[str(source_key)] = int(target_id)
        self.save()

    def save(self) -> None:
        self.data["updated_at"] = utc_now_iso()
        write_json(self.path, self.data, mode=0o600)


@dataclass(slots=True)
class Config:
    apply: bool
    strict: bool
    users_mode: str
    target_group_id: int | None
    target_group: str | None
    create_target_group: bool
    fallback_team: str | None
    multi_user_shift: str
    include_past_overrides: bool
    output_dir: Path


class Migrator:
    def __init__(
        self,
        source: dict[str, Any],
        ir: IncidentRelayClient,
        state: StateStore,
        reporter: Reporter,
        config: Config,
    ) -> None:
        self.source = source
        self.ir = ir
        self.state = state
        self.reporter = reporter
        self.config = config
        self.virtual_id = -1
        self.target_group: dict[str, Any] | None = None
        self.fallback_team_id: int | None = None
        self.secrets_path = config.output_dir / "route-secrets.json"
        self.route_secrets = read_json(self.secrets_path, default={"routes": []})

        self.groups: list[dict[str, Any]] = []
        self.teams: list[dict[str, Any]] = []
        self.users: list[dict[str, Any]] = []
        self.rotations: list[dict[str, Any]] = []
        self.policies: list[dict[str, Any]] = []
        self.routes: list[dict[str, Any]] = []

        self.group_members: dict[int, set[int]] = {}
        self.team_members: dict[int, set[int]] = {}
        self.layers: dict[int, list[dict[str, Any]]] = {}
        self.layer_members: dict[int, set[int]] = {}
        self.rotation_overrides: dict[int, list[dict[str, Any]]] = {}
        self.policy_rules: dict[int, list[dict[str, Any]]] = {}

        self.source_users = index_by_id(source.get("users", []))
        self.source_teams = index_by_id(source.get("teams", []))
        self.source_schedules = index_by_id(source.get("schedules", []))
        self.source_shifts = index_by_id(source.get("on_call_shifts", []))
        self.source_chains = index_by_id(source.get("escalation_chains", []))
        self.source_integrations = index_by_id(source.get("integrations", []))
        self.source_policies_by_chain: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for policy in source.get("escalation_policies", []):
            chain_id = scalar_id(policy.get("escalation_chain_id"))
            if chain_id:
                self.source_policies_by_chain[chain_id].append(policy)
        for policies in self.source_policies_by_chain.values():
            policies.sort(key=lambda item: int(item.get("position") or 0))

        self.source_routes_by_integration: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for route in source.get("routes", []):
            integration_id = scalar_id(route.get("integration_id"))
            if integration_id:
                self.source_routes_by_integration[integration_id].append(route)
        for routes in self.source_routes_by_integration.values():
            routes.sort(key=lambda item: int(item.get("position") or 0))

    def run(self) -> None:
        self.load_target()
        self.resolve_target_group()
        self.migrate_users()
        self.migrate_teams()
        self.migrate_memberships()
        self.resolve_fallback_team()
        self.migrate_schedules()
        self.migrate_team_scoped_chains()
        self.migrate_integrations_and_routes()
        if self.config.apply and self.route_secrets.get("routes"):
            write_json(self.secrets_path, self.route_secrets, mode=0o600)

    def load_target(self) -> None:
        self.groups = require_list(self.ir.get("/api/groups"), "IR groups")
        self.teams = require_list(
            self.ir.get("/api/teams", {"include_inactive": 1}),
            "IR teams",
        )
        self.users = require_list(self.ir.get("/api/admin/users"), "IR users")
        self.rotations = require_list(self.ir.get("/api/rotations"), "IR rotations")
        self.policies = require_list(
            self.ir.get("/api/escalation-policies"),
            "IR escalation policies",
        )
        self.routes = require_list(self.ir.get("/api/routes"), "IR routes")
        self.reporter.add(
            "info",
            "incidentrelay",
            "connected",
            "Loaded current IncidentRelay resources",
            groups=len(self.groups),
            teams=len(self.teams),
            users=len(self.users),
            rotations=len(self.rotations),
            policies=len(self.policies),
            routes=len(self.routes),
        )

    def resolve_target_group(self) -> None:
        candidate = None
        if self.config.target_group_id is not None:
            candidate = next(
                (
                    item
                    for item in self.groups
                    if int(item.get("id") or 0) == self.config.target_group_id
                ),
                None,
            )
        elif self.config.target_group:
            needle = self.config.target_group.casefold()
            candidate = next(
                (
                    item
                    for item in self.groups
                    if str(item.get("slug") or "").casefold() == needle
                    or str(item.get("name") or "").casefold() == needle
                ),
                None,
            )

        if candidate:
            self.target_group = candidate
            self.reporter.add(
                "info",
                "group",
                "adopted",
                f"Using existing target group {candidate.get('name')}",
                target_id=candidate.get("id"),
            )
            return

        if not self.config.target_group or not self.config.create_target_group:
            raise MigrationError(
                "target group was not found; pass --create-target-group to create it"
            )

        slug = unique_slug(
            self.config.target_group,
            {str(item.get("slug") or "") for item in self.groups},
        )
        payload = {
            "slug": slug,
            "name": self.config.target_group,
            "description": "Imported from Grafana OnCall",
            "active": True,
        }
        created = self.create_or_plan("group", self.config.target_group, "/api/groups", payload)
        self.target_group = created
        self.groups.append(created)

    def migrate_users(self) -> None:
        email_index = {
            str(item.get("email") or "").casefold(): item
            for item in self.users
            if item.get("email")
        }
        username_index = {
            str(item.get("username") or "").casefold(): item
            for item in self.users
            if item.get("username")
        }
        used_usernames = set(username_index)

        for source_id, source_user in self.source_users.items():
            mapped = self.state.get("users", source_id)
            if mapped:
                self.reporter.add(
                    "info",
                    "user",
                    "state",
                    "Using user mapping from state",
                    source_id,
                    target_id=mapped,
                )
                continue

            email = str(source_user.get("email") or "").strip()
            source_username = str(source_user.get("username") or "").strip()
            target = email_index.get(email.casefold()) if email else None
            if not target and source_username:
                target = username_index.get(source_username.casefold())

            if target:
                self.remember("users", source_id, int(target["id"]))
                self.reporter.add(
                    "info",
                    "user",
                    "adopted",
                    f"Matched existing user {target.get('username')}",
                    source_id,
                    target_id=target.get("id"),
                )
                continue

            if self.config.users_mode == "existing-only":
                self.reporter.add(
                    "warning",
                    "user",
                    "skipped",
                    "No matching IncidentRelay user; user creation is disabled",
                    source_id,
                    username=source_username,
                    email=email,
                )
                continue

            username = sanitize_username(
                source_username or email.split("@", 1)[0] or f"oncall-{source_id}",
                used_usernames,
                source_id,
            )
            used_usernames.add(username.casefold())
            slack_id = first_slack_user_id(source_user)
            payload = {
                "username": username,
                "display_name": source_username or username,
                "email": email or None,
                "phone": None,
                "telegram_user_id": None,
                "slack_user_id": slack_id,
                "mattermost_user_id": None,
                "active": False,
                "is_admin": False,
                "password": None,
                "group_id": int(self.target_group["id"]),
                "group_role": group_role_for(source_user.get("role")),
            }
            created = self.create_or_plan(
                "user",
                source_id,
                "/api/admin/users",
                payload,
            )
            self.users.append(created)
            if email:
                email_index[email.casefold()] = created
            username_index[username.casefold()] = created

    def migrate_teams(self) -> None:
        group_id = int(self.target_group["id"])
        existing_slugs = {
            str(item.get("slug") or "")
            for item in self.teams
            if int(item.get("group_id") or 0) == group_id
        }
        by_name = {
            str(item.get("name") or "").casefold(): item
            for item in self.teams
            if int(item.get("group_id") or 0) == group_id
        }

        for source_id, source_team in self.source_teams.items():
            mapped = self.state.get("teams", source_id)
            if mapped:
                continue
            name = str(source_team.get("name") or f"Grafana team {source_id}").strip()
            target = by_name.get(name.casefold())
            if target:
                self.remember("teams", source_id, int(target["id"]))
                self.reporter.add(
                    "info",
                    "team",
                    "adopted",
                    f"Matched existing team {name}",
                    source_id,
                    target_id=target.get("id"),
                )
                continue
            slug = unique_slug(name, existing_slugs)
            existing_slugs.add(slug)
            email = str(source_team.get("email") or "").strip()
            description = "Imported from Grafana OnCall"
            if email:
                description += f". Original team email: {email}"
            payload = {
                "group_id": group_id,
                "slug": slug,
                "name": name[:120],
                "description": description,
                "escalation_enabled": True,
                "escalation_after_reminders": 2,
                "active": True,
            }
            created = self.create_or_plan("team", source_id, "/api/teams", payload)
            self.teams.append(created)
            by_name[name.casefold()] = created

    def migrate_memberships(self) -> None:
        group_id = int(self.target_group["id"])
        for source_id, source_user in self.source_users.items():
            user_id = self.lookup("users", source_id)
            if not user_id:
                continue
            self.ensure_group_membership(
                group_id,
                user_id,
                group_role_for(source_user.get("role")),
            )
            for source_team_id in extract_ids(source_user.get("teams")):
                team_id = self.lookup("teams", source_team_id)
                if not team_id:
                    self.reporter.add(
                        "warning",
                        "team_membership",
                        "skipped",
                        "Source team is not mapped",
                        f"{source_id}:{source_team_id}",
                    )
                    continue
                self.ensure_team_membership(
                    team_id,
                    user_id,
                    team_role_for(source_user.get("role")),
                )

    def resolve_fallback_team(self) -> None:
        if self.config.fallback_team:
            needle = self.config.fallback_team.casefold()
            team = next(
                (
                    item
                    for item in self.teams
                    if str(item.get("slug") or "").casefold() == needle
                    or str(item.get("name") or "").casefold() == needle
                ),
                None,
            )
            if not team:
                raise MigrationError(
                    f"fallback team not found in IncidentRelay: {self.config.fallback_team}"
                )
            self.fallback_team_id = int(team["id"])
            return

        mapped_ids = {
            self.lookup("teams", source_id)
            for source_id in self.source_teams
        }
        mapped_ids.discard(None)
        if len(mapped_ids) == 1:
            self.fallback_team_id = int(next(iter(mapped_ids)))
            self.reporter.add(
                "info",
                "team",
                "fallback",
                "Using the only migrated team for teamless resources",
                target_id=self.fallback_team_id,
            )

    def migrate_schedules(self) -> None:
        for schedule_id, schedule in self.source_schedules.items():
            schedule_type = str(schedule.get("type") or "").lower()
            if schedule_type == "ical":
                self.reporter.add(
                    "warning",
                    "schedule",
                    "manual",
                    "External iCal schedules are not imported automatically",
                    schedule_id,
                    name=schedule.get("name"),
                    ical_url_primary=mask_url(schedule.get("ical_url_primary")),
                    ical_url_overrides=mask_url(schedule.get("ical_url_overrides")),
                )
                continue

            team_id = self.target_team_for_source(schedule.get("team_id"))
            if not team_id:
                self.reporter.add(
                    "warning",
                    "schedule",
                    "skipped",
                    "Schedule has no mapped team and no fallback team",
                    schedule_id,
                    name=schedule.get("name"),
                )
                continue

            shifts = self.schedule_shifts(schedule)
            rotation_id = self.ensure_rotation(schedule_id, schedule, shifts, team_id)
            if not rotation_id:
                continue
            for shift in shifts:
                shift_type = str(shift.get("type") or "").lower()
                if shift_type == "single_event":
                    self.ensure_override(schedule_id, rotation_id, shift)
                elif shift_type in {"rolling_users", "recurrent_event"}:
                    self.ensure_layer(schedule_id, rotation_id, shift)
                else:
                    self.reporter.add(
                        "warning",
                        "shift",
                        "skipped",
                        f"Unsupported shift type: {shift_type or 'unknown'}",
                        shift.get("id"),
                    )

    def migrate_team_scoped_chains(self) -> None:
        for chain_id, chain in self.source_chains.items():
            team_id = self.target_team_for_source(chain.get("team_id"))
            if not team_id:
                continue
            self.ensure_escalation_policy(chain_id, team_id)

    def migrate_integrations_and_routes(self) -> None:
        for integration_id, integration in self.source_integrations.items():
            team_id = self.target_team_for_source(integration.get("team_id"))
            if not team_id:
                self.reporter.add(
                    "warning",
                    "integration",
                    "skipped",
                    "Integration has no mapped team and no fallback team",
                    integration_id,
                    name=integration.get("name"),
                )
                continue

            routes = list(self.source_routes_by_integration.get(integration_id, []))
            default_route = integration.get("default_route")
            if isinstance(default_route, dict):
                default_id = scalar_id(default_route.get("id"))
                if default_id and all(scalar_id(item.get("id")) != default_id for item in routes):
                    routes.append(default_route)
            if not routes:
                routes = [{
                    "id": f"{integration_id}:default",
                    "integration_id": integration_id,
                    "escalation_chain_id": scalar_id(
                        (default_route or {}).get("escalation_chain_id")
                        if isinstance(default_route, dict)
                        else None
                    ),
                    "is_the_last_route": True,
                    "position": 0,
                }]
            routes.sort(key=lambda item: int(item.get("position") or 0))

            for route in routes:
                self.ensure_route(integration_id, integration, route, team_id)

    def ensure_rotation(
        self,
        schedule_id: str,
        schedule: Mapping[str, Any],
        shifts: list[dict[str, Any]],
        team_id: int,
    ) -> int | None:
        mapped = self.lookup("rotations", schedule_id)
        if mapped:
            return mapped
        name = str(schedule.get("name") or f"Grafana schedule {schedule_id}")[:120]
        existing = next(
            (
                item
                for item in self.rotations
                if int(item.get("team_id") or 0) == team_id
                and str(item.get("name") or "").casefold() == name.casefold()
            ),
            None,
        )
        if existing:
            self.remember("rotations", schedule_id, int(existing["id"]))
            self.reporter.add(
                "info",
                "rotation",
                "adopted",
                f"Matched existing rotation {name}",
                schedule_id,
                target_id=existing.get("id"),
            )
            return int(existing["id"])

        primary = next(
            (
                shift
                for shift in sorted(
                    shifts,
                    key=lambda item: int(item.get("level") or 0),
                    reverse=True,
                )
                if cadence_from_shift(shift) is not None
            ),
            None,
        )
        cadence = cadence_from_shift(primary or {}) or {
            "rotation_type": "daily",
            "interval_value": 1,
            "interval_unit": "days",
        }
        start = normalize_datetime(
            (primary or {}).get("start") or utc_now_iso()
        )
        dt = parse_datetime(start)
        timezone_name = str(
            (primary or {}).get("time_zone")
            or schedule.get("time_zone")
            or "UTC"
        )
        payload = {
            "team_id": team_id,
            "name": name,
            "description": "Imported from Grafana OnCall schedule",
            "start_at": start,
            **cadence,
            "handoff_time": dt.strftime("%H:%M"),
            "handoff_weekday": dt.weekday() if cadence["rotation_type"] == "weekly" else None,
            "timezone": timezone_name,
            "duration_seconds": None,
            "reminder_interval_seconds": 300,
            "add_team_members": False,
            "enabled": True,
        }
        created = self.create_or_plan(
            "rotation",
            schedule_id,
            "/api/rotations",
            payload,
        )
        self.rotations.append(created)
        return int(created["id"])

    def ensure_layer(
        self,
        schedule_id: str,
        rotation_id: int,
        shift: Mapping[str, Any],
    ) -> None:
        shift_id = scalar_id(shift.get("id")) or stable_key(shift)
        state_key = f"{schedule_id}:{shift_id}"
        cadence = cadence_from_shift(shift)
        if not cadence:
            self.reporter.add(
                "warning",
                "shift",
                "manual",
                "Monthly/unknown recurrence cannot be represented as an IncidentRelay layer",
                shift_id,
                frequency=shift.get("frequency"),
            )
            return

        member_groups = shift_member_groups(shift)
        member_ids: list[str] = []
        for group in member_groups:
            if len(group) > 1:
                if self.config.multi_user_shift == "skip":
                    self.reporter.add(
                        "warning",
                        "shift",
                        "manual",
                        "Shift contains simultaneous users; IncidentRelay layers rotate one user at a time",
                        shift_id,
                        users=group,
                    )
                    return
                self.reporter.add(
                    "warning",
                    "shift",
                    "degraded",
                    "Using only the first user from a simultaneous-user shift",
                    shift_id,
                    users=group,
                )
            if group:
                member_ids.append(group[0])

        mapped_users = [self.lookup("users", user_id) for user_id in member_ids]
        missing = [member_ids[index] for index, value in enumerate(mapped_users) if not value]
        if missing:
            self.reporter.add(
                "warning",
                "shift",
                "partial",
                "Some shift users are not mapped and will be omitted",
                shift_id,
                users=missing,
            )
        target_users = [int(value) for value in mapped_users if value]
        if not target_users:
            self.reporter.add(
                "warning",
                "shift",
                "skipped",
                "Shift has no mapped users",
                shift_id,
            )
            return

        layer_id = self.lookup("layers", state_key)
        if not layer_id:
            existing_layers = self.get_layers(rotation_id)
            name = str(shift.get("name") or f"Grafana shift {shift_id}")[:120]
            existing = next(
                (
                    item
                    for item in existing_layers
                    if str(item.get("name") or "").casefold() == name.casefold()
                ),
                None,
            )
            if existing:
                layer_id = int(existing["id"])
                self.remember("layers", state_key, layer_id)
            else:
                start = normalize_datetime(shift.get("start") or utc_now_iso())
                dt = parse_datetime(start)
                rotation_timezone = next(
                    (
                        item.get("timezone")
                        for item in self.rotations
                        if int(item.get("id") or 0) == rotation_id
                    ),
                    None,
                )
                payload = {
                    "name": name,
                    "description": "Imported from Grafana OnCall shift",
                    "priority": max(0, int(shift.get("level") or 0)),
                    "start_at": start,
                    **cadence,
                    "handoff_time": dt.strftime("%H:%M"),
                    "handoff_weekday": dt.weekday() if cadence["rotation_type"] == "weekly" else None,
                    "timezone": str(shift.get("time_zone") or rotation_timezone or "UTC"),
                    "duration_seconds": None,
                    "enabled": True,
                }
                created = self.create_or_plan(
                    "layer",
                    state_key,
                    f"/api/rotations/{rotation_id}/layers",
                    payload,
                )
                layer_id = int(created["id"])
                self.layers.setdefault(rotation_id, []).append(created)

        current_members = self.get_layer_members(layer_id)
        for position, user_id in enumerate(target_users):
            if user_id in current_members:
                continue
            payload = {"user_id": user_id, "position": position, "starts_at": None}
            self.post_or_plan(
                "layer_member",
                f"{state_key}:{user_id}",
                f"/api/rotations/layers/{layer_id}/members",
                payload,
            )
            current_members.add(user_id)

        restrictions = restrictions_from_shift(shift)
        if (shift.get("by_day") or []) and restrictions is None:
            duration = max(60, int(shift.get("duration") or 0))
            if duration < 86400:
                self.reporter.add(
                    "warning",
                    "shift",
                    "manual",
                    "Cross-midnight schedule restriction requires manual review",
                    shift_id,
                )
        if restrictions is not None:
            self.put_or_plan(
                "layer_restrictions",
                state_key,
                f"/api/rotations/layers/{layer_id}/restrictions",
                {"restrictions": restrictions},
            )

    def ensure_override(
        self,
        schedule_id: str,
        rotation_id: int,
        shift: Mapping[str, Any],
    ) -> None:
        shift_id = scalar_id(shift.get("id")) or stable_key(shift)
        state_key = f"{schedule_id}:{shift_id}"
        if self.lookup("overrides", state_key):
            return
        groups = shift_member_groups(shift)
        users = [item for group in groups for item in group]
        if len(users) != 1:
            if users and self.config.multi_user_shift == "first":
                self.reporter.add(
                    "warning",
                    "override",
                    "degraded",
                    "Using first user from a multi-user single event",
                    shift_id,
                    users=users,
                )
                users = users[:1]
            else:
                self.reporter.add(
                    "warning",
                    "override",
                    "manual",
                    "Single event must contain exactly one user",
                    shift_id,
                    users=users,
                )
                return
        user_id = self.lookup("users", users[0])
        if not user_id:
            self.reporter.add(
                "warning",
                "override",
                "skipped",
                "Override user is not mapped",
                shift_id,
                user=users[0],
            )
            return
        starts_at = parse_datetime(normalize_datetime(shift.get("start")))
        duration = max(60, int(shift.get("duration") or 0))
        ends_at = starts_at + timedelta(seconds=duration)
        if not self.config.include_past_overrides and ends_at < datetime.now(timezone.utc):
            self.reporter.add(
                "info",
                "override",
                "skipped",
                "Past single event was not imported",
                shift_id,
            )
            return
        payload = {
            "user_id": user_id,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "reason": f"Imported from Grafana OnCall shift {shift_id}",
        }
        created = self.create_or_plan(
            "override",
            state_key,
            f"/api/rotations/{rotation_id}/overrides",
            payload,
        )
        self.rotation_overrides.setdefault(rotation_id, []).append(created)

    def ensure_escalation_policy(self, chain_id: str, team_id: int) -> int | None:
        state_key = f"{chain_id}:{team_id}"
        mapped = self.lookup("escalation_policies", state_key)
        if mapped:
            return mapped
        chain = self.source_chains.get(chain_id)
        if not chain:
            self.reporter.add(
                "warning",
                "escalation_chain",
                "skipped",
                "Referenced escalation chain was not returned by Grafana OnCall",
                chain_id,
            )
            return None

        rules = self.convert_chain_rules(chain_id, team_id)
        if not rules:
            self.reporter.add(
                "warning",
                "escalation_chain",
                "manual",
                "Chain has no safely convertible notification steps",
                chain_id,
                name=chain.get("name"),
            )
            return None

        name = str(chain.get("name") or f"Grafana chain {chain_id}")[:120]
        existing = next(
            (
                item
                for item in self.policies
                if int(item.get("team_id") or 0) == team_id
                and str(item.get("name") or "").casefold() == name.casefold()
            ),
            None,
        )
        if existing:
            policy_id = int(existing["id"])
            self.remember("escalation_policies", state_key, policy_id)
            self.reporter.add(
                "info",
                "escalation_policy",
                "adopted",
                f"Matched existing policy {name}",
                chain_id,
                target_id=policy_id,
            )
        else:
            payload = {
                "team_id": team_id,
                "name": name,
                "description": f"Imported from Grafana OnCall chain {chain_id}",
                "enabled": True,
                "repeat_count": 0,
            }
            created = self.create_or_plan(
                "escalation_policy",
                state_key,
                "/api/escalation-policies",
                payload,
            )
            policy_id = int(created["id"])
            self.policies.append(created)

        current = self.get_policy_rules(policy_id)
        for rule in rules:
            if any(rule_equivalent(rule, item) for item in current):
                continue
            created = self.post_or_plan(
                "escalation_rule",
                f"{state_key}:{rule['source_step_id']}",
                f"/api/escalation-policies/{policy_id}/rules",
                {key: value for key, value in rule.items() if key != "source_step_id"},
            )
            current.append(created)
        return policy_id

    def convert_chain_rules(self, chain_id: str, team_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        delay = 0
        position = 1
        for step in self.source_policies_by_chain.get(chain_id, []):
            step_id = scalar_id(step.get("id")) or stable_key(step)
            step_type = str(step.get("type") or "")
            if step_type == "wait":
                delay += max(0, int(step.get("duration") or 0))
                continue

            target_type: str | None = None
            target_id: int | None = None
            if step_type == "notify_on_call_from_schedule":
                schedule_id = first_scalar_id(
                    step.get("notify_on_call_from_schedule"),
                    step.get("schedule_to_notify"),
                )
                target_id = self.lookup("rotations", schedule_id) if schedule_id else None
                target_type = "rotation"
            elif step_type in {"notify_persons", "notify_person_next_each_time"}:
                values = (
                    step.get("persons_to_notify")
                    if step_type == "notify_persons"
                    else step.get("persons_to_notify_next_each_time")
                )
                user_ids = extract_ids(values)
                if len(user_ids) != 1:
                    if user_ids and self.config.multi_user_shift == "first":
                        self.reporter.add(
                            "warning",
                            "escalation_step",
                            "degraded",
                            "Using first user from a multi-user escalation step",
                            step_id,
                            users=user_ids,
                        )
                        user_ids = user_ids[:1]
                    else:
                        self.reporter.add(
                            "warning",
                            "escalation_step",
                            "manual",
                            "Multi-user escalation notification has no exact IncidentRelay equivalent",
                            step_id,
                            users=user_ids,
                        )
                        continue
                target_id = self.lookup("users", user_ids[0]) if user_ids else None
                target_type = "user"
            else:
                self.reporter.add(
                    "warning",
                    "escalation_step",
                    "manual",
                    f"Unsupported Grafana OnCall escalation step: {step_type}",
                    step_id,
                )
                continue

            if not target_id:
                self.reporter.add(
                    "warning",
                    "escalation_step",
                    "skipped",
                    "Escalation target is not mapped",
                    step_id,
                    target_type=target_type,
                )
                continue
            result.append(
                {
                    "source_step_id": step_id,
                    "position": position,
                    "delay_seconds": min(delay, 86400),
                    "target_type": target_type,
                    "target_id": int(target_id),
                    "enabled": True,
                }
            )
            position += 1
            delay = 0

        if delay:
            self.reporter.add(
                "warning",
                "escalation_chain",
                "manual",
                "Trailing wait step has no following notification and was omitted",
                chain_id,
                delay_seconds=delay,
            )
        return result

    def ensure_route(
        self,
        integration_id: str,
        integration: Mapping[str, Any],
        route: Mapping[str, Any],
        team_id: int,
    ) -> None:
        source_route_id = scalar_id(route.get("id")) or stable_key(route)
        state_key = f"{integration_id}:{source_route_id}"
        if self.lookup("routes", state_key):
            return

        position = int(route.get("position") or 0)
        is_default = bool(route.get("is_the_last_route")) or route is integration.get("default_route")
        routing_value = str(route.get("routing_regex") or "").strip()
        routing_type = str(route.get("routing_type") or "regex")
        safe_default = is_default or not routing_value
        enabled = safe_default
        if routing_value:
            self.reporter.add(
                "warning",
                "route",
                "manual",
                "Grafana whole-payload regex/Jinja routing cannot be converted to IncidentRelay label matchers; route is created disabled",
                source_route_id,
                routing_type=routing_type,
                routing_expression=routing_value[:300],
            )
            enabled = False

        chain_id = scalar_id(route.get("escalation_chain_id"))
        policy_id = self.ensure_escalation_policy(chain_id, team_id) if chain_id else None
        rotation_id = self.first_rotation_for_team(team_id)
        source = normalize_source_type(integration.get("type"))
        if source not in SUPPORTED_IR_SOURCES or source in {"sentry"}:
            self.reporter.add(
                "warning",
                "integration",
                "degraded",
                "Integration type is migrated as a disabled generic webhook",
                integration_id,
                source_type=integration.get("type"),
            )
            source = "webhook"
            enabled = False

        base_name = str(integration.get("name") or f"Grafana integration {integration_id}")
        suffix = "" if safe_default else f" / route {position + 1}"
        name = (base_name + suffix)[:120]
        existing = next(
            (
                item
                for item in self.routes
                if int(item.get("team_id") or 0) == team_id
                and str(item.get("name") or "").casefold() == name.casefold()
            ),
            None,
        )
        if existing:
            self.remember("routes", state_key, int(existing["id"]))
            self.reporter.add(
                "info",
                "route",
                "adopted",
                f"Matched existing route {name}",
                source_route_id,
                target_id=existing.get("id"),
            )
            return

        payload = {
            "team_id": team_id,
            "name": name,
            "source": source,
            "rotation_id": rotation_id,
            "channel_ids": [],
            "notification_channel_mode": "route_only",
            "matcher_preset_id": None,
            "matchers": {},
            "group_by": [],
            "integration_config": {},
            "enabled": enabled,
            "escalation_mode": "policy" if policy_id else "rotation",
            "escalation_policy_id": policy_id,
            "service_id": None,
        }
        created = self.create_or_plan(
            "route",
            state_key,
            "/api/routes",
            payload,
        )
        self.routes.append(created)
        if self.config.apply:
            token = created.get("intake_token")
            if token:
                route_id = int(created["id"])
                secret_entry = {
                    "source_integration_id": integration_id,
                    "source_route_id": source_route_id,
                    "source_name": base_name,
                    "old_url": integration.get("link"),
                    "ir_route_id": route_id,
                    "ir_route_name": name,
                    "ir_source": source,
                    "new_url": intake_url(self.ir.base_url, source, route_id),
                    "authorization": f"Bearer {token}",
                    "enabled": enabled,
                }
                replace_secret_entry(self.route_secrets["routes"], secret_entry)
                self.reporter.add(
                    "info",
                    "route",
                    "secret_saved",
                    "New intake URL and token were saved to route-secrets.json",
                    source_route_id,
                    target_id=route_id,
                )

    def target_team_for_source(self, source_team: Any) -> int | None:
        source_id = scalar_id(source_team)
        if source_id:
            mapped = self.lookup("teams", source_id)
            if mapped:
                return mapped
        return self.fallback_team_id

    def schedule_shifts(self, schedule: Mapping[str, Any]) -> list[dict[str, Any]]:
        shift_ids = extract_ids(schedule.get("shifts"))
        if shift_ids:
            return [self.source_shifts[item] for item in shift_ids if item in self.source_shifts]
        schedule_id = scalar_id(schedule.get("id"))
        return [
            shift
            for shift in self.source_shifts.values()
            if schedule_id in extract_ids(
                shift.get("schedule_id") or shift.get("schedule") or shift.get("schedules")
            )
        ]

    def first_rotation_for_team(self, team_id: int) -> int | None:
        for item in self.rotations:
            if int(item.get("team_id") or 0) == team_id and item.get("enabled", True):
                return int(item["id"])
        return None

    def ensure_group_membership(self, group_id: int, user_id: int, role: str) -> None:
        members = self.group_members.get(group_id)
        if members is None:
            if group_id < 0:
                members = set()
            else:
                members = {
                    int(item["user_id"])
                    for item in require_list(
                        self.ir.get(f"/api/groups/{group_id}/users"),
                        "IR group users",
                    )
                }
            self.group_members[group_id] = members
        if user_id in members:
            return
        self.post_or_plan(
            "group_membership",
            f"{group_id}:{user_id}",
            f"/api/groups/{group_id}/users",
            {"user_id": user_id, "role": role, "active": True},
        )
        members.add(user_id)

    def ensure_team_membership(self, team_id: int, user_id: int, role: str) -> None:
        members = self.team_members.get(team_id)
        if members is None:
            if team_id < 0:
                members = set()
            else:
                members = {
                    int(item["user_id"])
                    for item in require_list(
                        self.ir.get(f"/api/teams/{team_id}/users"),
                        "IR team users",
                    )
                }
            self.team_members[team_id] = members
        if user_id in members:
            return
        self.post_or_plan(
            "team_membership",
            f"{team_id}:{user_id}",
            f"/api/teams/{team_id}/users",
            {"user_id": user_id, "role": role, "active": True},
        )
        members.add(user_id)

    def get_layers(self, rotation_id: int) -> list[dict[str, Any]]:
        if rotation_id not in self.layers:
            if rotation_id < 0:
                self.layers[rotation_id] = []
            else:
                self.layers[rotation_id] = require_list(
                    self.ir.get(f"/api/rotations/{rotation_id}/layers"),
                    "IR rotation layers",
                )
        return self.layers[rotation_id]

    def get_layer_members(self, layer_id: int) -> set[int]:
        if layer_id not in self.layer_members:
            if layer_id < 0:
                self.layer_members[layer_id] = set()
            else:
                self.layer_members[layer_id] = {
                    int(item["user_id"])
                    for item in require_list(
                        self.ir.get(f"/api/rotations/layers/{layer_id}/members"),
                        "IR layer members",
                    )
                }
        return self.layer_members[layer_id]

    def get_policy_rules(self, policy_id: int) -> list[dict[str, Any]]:
        if policy_id not in self.policy_rules:
            if policy_id < 0:
                self.policy_rules[policy_id] = []
            else:
                self.policy_rules[policy_id] = require_list(
                    self.ir.get(f"/api/escalation-policies/{policy_id}/rules"),
                    "IR escalation rules",
                )
        return self.policy_rules[policy_id]

    def create_or_plan(
        self,
        entity: str,
        source_key: Any,
        path: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.config.apply:
            created = self.ir.post(path, payload)
            if not isinstance(created, dict) or "id" not in created:
                raise MigrationError(f"IncidentRelay did not return an id for {entity}")
            self.remember(entity_plural(entity), source_key, int(created["id"]))
            self.reporter.add(
                "info",
                entity,
                "created",
                "Created in IncidentRelay",
                source_key,
                target_id=created.get("id"),
            )
            return created
        result = {"id": self.next_virtual_id(), **dict(payload)}
        self.remember(entity_plural(entity), source_key, int(result["id"]))
        self.reporter.add(
            "plan",
            entity,
            "create",
            "Would create in IncidentRelay",
            source_key,
            payload=redact_payload(payload),
        )
        return result

    def post_or_plan(
        self,
        entity: str,
        source_key: Any,
        path: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.config.apply:
            created = self.ir.post(path, payload)
            if not isinstance(created, dict):
                created = {"result": created}
            self.reporter.add(
                "info",
                entity,
                "created",
                "Created in IncidentRelay",
                source_key,
                target_id=created.get("id"),
            )
            return created
        result = {"id": self.next_virtual_id(), **dict(payload)}
        self.reporter.add(
            "plan",
            entity,
            "create",
            "Would create in IncidentRelay",
            source_key,
            payload=redact_payload(payload),
        )
        return result

    def put_or_plan(
        self,
        entity: str,
        source_key: Any,
        path: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.config.apply:
            result = self.ir.put(path, payload)
            self.reporter.add(
                "info",
                entity,
                "updated",
                "Updated in IncidentRelay",
                source_key,
            )
            return result if isinstance(result, dict) else {"result": result}
        self.reporter.add(
            "plan",
            entity,
            "update",
            "Would update in IncidentRelay",
            source_key,
            payload=redact_payload(payload),
        )
        return dict(payload)

    def lookup(self, category: str, source_key: Any) -> int | None:
        if source_key is None:
            return None
        return self.state.get(category, source_key) or getattr(
            self,
            f"_dry_{category}",
            {},
        ).get(str(source_key))

    def remember(self, category: str, source_key: Any, target_id: int) -> None:
        if self.config.apply:
            self.state.set(category, source_key, target_id)
        else:
            mapping = getattr(self, f"_dry_{category}", None)
            if mapping is None:
                mapping = {}
                setattr(self, f"_dry_{category}", mapping)
            mapping[str(source_key)] = int(target_id)

    def next_virtual_id(self) -> int:
        value = self.virtual_id
        self.virtual_id -= 1
        return value


def entity_plural(entity: str) -> str:
    aliases = {
        "policy": "escalation_policies",
        "escalation_policy": "escalation_policies",
        "rotation": "rotations",
        "layer": "layers",
        "override": "overrides",
        "route": "routes",
        "user": "users",
        "team": "teams",
        "group": "groups",
    }
    return aliases.get(entity, entity + "s")


def index_by_id(items: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = scalar_id(item.get("id"))
        if item_id:
            result[item_id] = dict(item)
    return result


def scalar_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def first_scalar_id(*values: Any) -> str | None:
    for value in values:
        item = scalar_id(value)
        if item:
            return item
    return None


def extract_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int)):
        item = scalar_id(value)
        return [item] if item else []
    if isinstance(value, Mapping):
        item = scalar_id(value)
        return [item] if item else []
    result: list[str] = []
    if isinstance(value, Iterable):
        for item in value:
            item_id = scalar_id(item)
            if item_id:
                result.append(item_id)
    return result


def shift_member_groups(shift: Mapping[str, Any]) -> list[list[str]]:
    if str(shift.get("type") or "") == "rolling_users":
        raw = shift.get("rolling_users") or []
        result: list[list[str]] = []
        for group in raw:
            result.append(extract_ids(group))
        start_index = int(shift.get("start_rotation_from_user_index") or 0)
        if result and start_index:
            start_index %= len(result)
            result = result[start_index:] + result[:start_index]
        return result
    users = extract_ids(shift.get("users"))
    return [users] if users else []


def cadence_from_shift(shift: Mapping[str, Any]) -> dict[str, Any] | None:
    frequency = str(shift.get("frequency") or "").lower()
    interval = max(1, int(shift.get("interval") or 1))
    if frequency == "hourly":
        return {
            "rotation_type": "custom",
            "interval_value": interval,
            "interval_unit": "hours",
        }
    if frequency == "daily":
        if interval == 1:
            return {
                "rotation_type": "daily",
                "interval_value": 1,
                "interval_unit": "days",
            }
        return {
            "rotation_type": "custom",
            "interval_value": interval,
            "interval_unit": "days",
        }
    if frequency == "weekly":
        if interval == 1:
            return {
                "rotation_type": "weekly",
                "interval_value": 1,
                "interval_unit": "weeks",
            }
        return {
            "rotation_type": "custom",
            "interval_value": interval,
            "interval_unit": "weeks",
        }
    return None


def restrictions_from_shift(shift: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    days = [WEEKDAY_MAP[item] for item in shift.get("by_day") or [] if item in WEEKDAY_MAP]
    if not days:
        return None
    duration = max(60, int(shift.get("duration") or 0))
    if duration >= 86400:
        return None
    start = parse_datetime(normalize_datetime(shift.get("start")))
    end = start + timedelta(seconds=duration)
    if end.date() != start.date() and duration < 86400:
        # Cross-midnight restrictions need two records per weekday and would
        # change week-boundary semantics. Leave them for manual review.
        return None
    return [
        {
            "weekday": weekday,
            "start_time": start.strftime("%H:%M"),
            "end_time": end.strftime("%H:%M") if duration < 86400 else start.strftime("%H:%M"),
        }
        for weekday in days
    ]


def normalize_source_type(value: Any) -> str:
    source = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "prometheus_alertmanager": "alertmanager",
        "prometheus": "alertmanager",
        "alertmanager": "alertmanager",
        "grafana": "grafana",
        "grafana_alerting": "grafana",
        "webhook": "webhook",
        "formatted_webhook": "webhook",
        "zabbix": "zabbix",
        "sentry": "sentry",
        "librenms": "librenms",
        "rmon": "rmon",
    }
    return aliases.get(source, source)


def group_role_for(role: Any) -> str:
    return "editor" if str(role or "").lower() == "admin" else "viewer"


def team_role_for(role: Any) -> str:
    role = str(role or "").lower()
    if role == "admin":
        return "manager"
    if role == "observer":
        return "viewer"
    return "responder"


def first_slack_user_id(user: Mapping[str, Any]) -> str | None:
    slack = user.get("slack")
    if not isinstance(slack, list):
        return None
    for item in slack:
        if isinstance(item, Mapping) and item.get("user_id"):
            return str(item["user_id"])
    return None


def sanitize_username(value: str, used: set[str], source_id: str) -> str:
    username = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    if len(username) < 2:
        username = f"oncall-{source_id.lower()}"
    username = username[:120]
    candidate = username
    suffix = 2
    while candidate.casefold() in used:
        tail = f"-{suffix}"
        candidate = username[: 120 - len(tail)] + tail
        suffix += 1
    return candidate


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"[-_]{2,}", "-", value).strip("-_")
    if not value or not value[0].isalnum():
        value = "imported-" + value
    return value[:120] or "imported"


def unique_slug(value: str, existing: set[str]) -> str:
    base = slugify(value)
    candidate = base
    suffix = 2
    while candidate in existing:
        tail = f"-{suffix}"
        candidate = base[: 120 - len(tail)] + tail
        suffix += 1
    return candidate


def normalize_datetime(value: Any) -> str:
    if not value:
        return utc_now_iso()
    text = str(value).strip()
    if text.endswith("Z"):
        return text[:-1] + "+00:00"
    return text


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MigrationError(f"invalid datetime from Grafana OnCall: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def rule_equivalent(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    return all(
        actual.get(key) == expected.get(key)
        for key in ("position", "delay_seconds", "target_type", "target_id", "enabled")
    )


def stable_key(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def intake_url(base_url: str, source: str, route_id: int) -> str:
    if source == "sentry":
        return f"{base_url}/api/integrations/sentry/{route_id}"
    return f"{base_url}/api/integrations/{source.replace('_', '-')}"


def replace_secret_entry(items: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    key = (entry["source_integration_id"], entry["source_route_id"])
    for index, current in enumerate(items):
        if (current.get("source_integration_id"), current.get("source_route_id")) == key:
            items[index] = entry
            return
    items.append(entry)


def mask_url(value: Any) -> str | None:
    if not value:
        return None
    parsed = urlparse(str(value))
    return f"{parsed.scheme}://{parsed.netloc}/…" if parsed.scheme and parsed.netloc else "…"


def redact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(payload, default=str))
    for key in list(redacted):
        if any(part in key.lower() for part in ("token", "password", "secret", "authorization")):
            redacted[key] = "***"
    return redacted


def require_list(value: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return [item for item in value["items"] if isinstance(item, dict)]
    raise MigrationError(f"unexpected {label} response")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        if mode is not None:
            os.chmod(path, mode)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate Grafana OnCall OSS configuration to IncidentRelay",
    )
    parser.add_argument("--oncall-url", required=True, help="Grafana OnCall application API URL")
    parser.add_argument("--ir-url", required=True, help="IncidentRelay base URL")
    parser.add_argument(
        "--oncall-token",
        default=os.getenv("GRAFANA_ONCALL_TOKEN"),
        help="Grafana OnCall API key; defaults to GRAFANA_ONCALL_TOKEN",
    )
    parser.add_argument(
        "--ir-token",
        default=os.getenv("INCIDENTRELAY_TOKEN"),
        help="IncidentRelay admin API token; defaults to INCIDENTRELAY_TOKEN",
    )
    parser.add_argument(
        "--grafana-url",
        default=os.getenv("GRAFANA_URL"),
        help="X-Grafana-URL value when using a Grafana service-account token",
    )
    parser.add_argument("--target-group-id", type=int)
    parser.add_argument(
        "--target-group",
        help="Existing IncidentRelay group slug/name, or new group name with --create-target-group",
    )
    parser.add_argument("--create-target-group", action="store_true")
    parser.add_argument(
        "--fallback-team",
        help="IncidentRelay team slug/name for teamless Grafana resources",
    )
    parser.add_argument(
        "--users-mode",
        choices=("existing-only", "create-inactive"),
        default="existing-only",
    )
    parser.add_argument(
        "--multi-user-shift",
        choices=("skip", "first"),
        default="skip",
        help="How to handle simultaneous users where IR supports one target",
    )
    parser.add_argument("--include-past-overrides", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Create resources; default is dry-run")
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Fail on the first warning")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("migration-output"),
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Mapping state file; defaults to <output-dir>/state.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.oncall_token:
        parser.error("--oncall-token or GRAFANA_ONCALL_TOKEN is required")
    if not args.ir_token and not args.snapshot_only:
        parser.error("--ir-token or INCIDENTRELAY_TOKEN is required")
    if not args.snapshot_only and not (args.target_group_id or args.target_group):
        parser.error("--target-group-id or --target-group is required")

    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    reporter = Reporter(strict=args.strict)
    mode = "apply" if args.apply else "dry-run"
    metadata = {
        "mode": mode,
        "generated_at": utc_now_iso(),
        "oncall_url": args.oncall_url.rstrip("/"),
        "ir_url": args.ir_url.rstrip("/"),
    }

    try:
        oncall = GrafanaOnCallClient(
            args.oncall_url,
            args.oncall_token,
            grafana_url=args.grafana_url,
            verify_tls=not args.insecure,
        )
        snapshot = oncall.snapshot(reporter)
        source_dir = output_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        for name, value in snapshot.items():
            write_json(source_dir / f"{name}.json", value, mode=0o600)
        write_json(output_dir / "snapshot.json", snapshot, mode=0o600)

        if args.snapshot_only:
            reporter.write(output_dir, metadata)
            print(f"Snapshot written to {output_dir}")
            return 0

        state_path = (args.state_file or output_dir / "state.json").resolve()
        state = StateStore(state_path, args.oncall_url, args.ir_url)
        ir = IncidentRelayClient(
            args.ir_url,
            args.ir_token,
            verify_tls=not args.insecure,
        )
        config = Config(
            apply=args.apply,
            strict=args.strict,
            users_mode=args.users_mode,
            target_group_id=args.target_group_id,
            target_group=args.target_group,
            create_target_group=args.create_target_group,
            fallback_team=args.fallback_team,
            multi_user_shift=args.multi_user_shift,
            include_past_overrides=args.include_past_overrides,
            output_dir=output_dir,
        )
        Migrator(snapshot, ir, state, reporter, config).run()
        reporter.write(output_dir, metadata)
        print(f"Migration {mode} completed. Report: {output_dir / 'report.md'}")
        if args.apply:
            print(f"State: {state_path}")
            if (output_dir / "route-secrets.json").is_file():
                print(f"Route secrets: {output_dir / 'route-secrets.json'}")
        return 0
    except (MigrationError, ApiError, json.JSONDecodeError) as exc:
        reporter.add("error", "migration", "failed", str(exc))
        reporter.write(output_dir, metadata)
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
