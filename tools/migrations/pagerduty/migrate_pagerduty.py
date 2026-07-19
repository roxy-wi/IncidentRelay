#!/usr/bin/env python3
"""Migrate PagerDuty configuration to IncidentRelay through public HTTP APIs.

The command is dry-run by default. It does not connect to either database and
never writes API tokens to the report. In --apply mode, generated IncidentRelay
route intake tokens are stored only in a chmod-0600 JSON file.

Supported in this first version:
- users and group membership;
- PagerDuty teams and memberships;
- legacy PagerDuty schedules, layers, restrictions and future overrides;
- escalation policies;
- services and PagerDuty Events API v2-compatible Webhook routes;
- active/future maintenance windows;
- source snapshots, resumable state and migration reports.

Not imported in this version:
- incident/alert history;
- Event Orchestrations and Rulesets;
- PagerDuty V3 shift-based schedules (reported for manual handling);
- notification/contact methods and notification rules.
"""

from __future__ import annotations

import argparse
import csv
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
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


STATE_VERSION = 1
DEFAULT_PD_URL = "https://api.pagerduty.com"
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 5
DEFAULT_PAGE_SIZE = 100
MIGRATION_STAGES = (
    "users",
    "teams",
    "schedules",
    "policies",
    "services",
    "maintenance",
)


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
    """Collect actions and warnings without storing secrets."""

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
        return {
            "events": len(self.events),
            "levels": dict(sorted(Counter(item.level for item in self.events).items())),
            "actions": dict(
                sorted(Counter(f"{item.entity}:{item.action}" for item in self.events).items())
            ),
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
            "# PagerDuty → IncidentRelay migration report",
            "",
            f"- Mode: **{metadata.get('mode')}**",
            f"- Generated: `{metadata.get('generated_at')}`",
            f"- PagerDuty API: `{metadata.get('pagerduty_url')}`",
            f"- IncidentRelay: `{metadata.get('incidentrelay_url')}`",
            f"- Target group ID: `{metadata.get('group_id')}`",
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
                f"- **{event.level.upper()}** `{event.entity}`{source} — {event.message}"
            )
            for key, value in event.details.items():
                lines.append(f"  - {key}: `{json_scalar(value)}`")
        (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class JsonHttpClient:
    """Small JSON client with TLS verification and retry handling."""

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

        safe_url = redact_url(url)
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            request = Request(url, data=data, headers=headers, method=method.upper())
            try:
                with urlopen(
                    request,
                    timeout=self.timeout,
                    context=self.ssl_context,
                ) as response:
                    status = response.status
                    raw = response.read()
                    payload = parse_json_bytes(raw)
                    if status not in set(expected):
                        raise ApiError(method, safe_url, status, api_message(payload), payload)
                    return payload
            except HTTPError as exc:
                raw = exc.read()
                payload = parse_json_bytes(raw)
                last_error = ApiError(
                    method,
                    safe_url,
                    exc.code,
                    api_message(payload) or str(exc),
                    payload,
                )
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.retries:
                    raise last_error from exc
                delay = retry_delay(exc.headers, attempt)
                print(f"RETRY   HTTP {exc.code}; retrying in {delay:.1f}s")
                time.sleep(delay)
            except (URLError, TimeoutError, OSError) as exc:
                last_error = ApiError(method, safe_url, None, str(exc))
                if attempt >= self.retries:
                    raise last_error from exc
                delay = min(2**attempt, 20)
                print(f"RETRY   network error; retrying in {delay:.1f}s")
                time.sleep(delay)

        if last_error:
            raise last_error
        raise MigrationError(f"request failed unexpectedly: {method} {safe_url}")


class PagerDutyClient:
    """PagerDuty REST API v2 client."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        from_email: str | None = None,
        verify_tls: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        headers = {
            "Authorization": f"Token token={token}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "User-Agent": "IncidentRelay-PagerDuty-Migrator/1.0",
        }
        if from_email:
            headers["From"] = from_email
        self.http = JsonHttpClient(
            base_url,
            headers,
            verify_tls=verify_tls,
            timeout=timeout,
            retries=retries,
        )

    def paginate(
        self,
        path: str,
        collection_key: str,
        *,
        query: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        offset = 0
        items: list[dict[str, Any]] = []
        base_query = dict(query or {})
        while True:
            payload = self.http.request(
                "GET",
                path,
                query={**base_query, "limit": DEFAULT_PAGE_SIZE, "offset": offset},
            )
            page = as_list(payload.get(collection_key) if isinstance(payload, dict) else None)
            items.extend(item for item in page if isinstance(item, dict))
            if not bool(payload.get("more")):
                break
            limit = int(payload.get("limit") or DEFAULT_PAGE_SIZE)
            offset = int(payload.get("offset") or offset) + limit
        return items

    def users(self) -> list[dict[str, Any]]:
        return self.paginate("/users", "users")

    def teams(self) -> list[dict[str, Any]]:
        return self.paginate("/teams", "teams")

    def team_members(self, team_id: str) -> list[dict[str, Any]]:
        return self.paginate(f"/teams/{team_id}/members", "members")

    def schedules(self) -> list[dict[str, Any]]:
        return self.paginate("/schedules", "schedules")

    def schedule(self, schedule_id: str) -> dict[str, Any]:
        payload = self.http.request(
            "GET",
            f"/schedules/{schedule_id}",
            query={"include[]": ["teams"]},
        )
        return dict(payload.get("schedule") or {})

    def schedule_overrides(
        self,
        schedule_id: str,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]]:
        payload = self.http.request(
            "GET",
            f"/schedules/{schedule_id}/overrides",
            query={"since": iso_z(since), "until": iso_z(until), "overflow": "true"},
        )
        return [item for item in as_list(payload.get("overrides")) if isinstance(item, dict)]

    def escalation_policies(self) -> list[dict[str, Any]]:
        return self.paginate(
            "/escalation_policies",
            "escalation_policies",
            query={"include[]": ["teams", "services", "targets"]},
        )

    def escalation_policy(self, policy_id: str) -> dict[str, Any]:
        payload = self.http.request(
            "GET",
            f"/escalation_policies/{policy_id}",
            query={"include[]": ["teams", "services", "targets"]},
        )
        return dict(payload.get("escalation_policy") or {})

    def services(self) -> list[dict[str, Any]]:
        return self.paginate(
            "/services",
            "services",
            query={"include[]": ["teams", "escalation_policies", "integrations"]},
        )

    def maintenance_windows(self) -> list[dict[str, Any]]:
        return self.paginate(
            "/maintenance_windows",
            "maintenance_windows",
            query={"include[]": ["teams", "services"]},
        )

    def v3_schedules(self) -> list[dict[str, Any]]:
        """Best-effort inventory only; V3 schedules are not imported."""
        try:
            payload = self.http.request(
                "GET",
                "/v3/schedules",
                query={"limit": DEFAULT_PAGE_SIZE},
            )
        except ApiError as exc:
            if exc.status in {400, 403, 404, 406, 422}:
                return []
            raise
        if isinstance(payload, dict):
            for key in ("schedules", "data"):
                if isinstance(payload.get(key), list):
                    return [item for item in payload[key] if isinstance(item, dict)]
        return []


class IncidentRelayClient:
    """IncidentRelay public API client."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        verify_tls: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = JsonHttpClient(
            self.base_url,
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": "IncidentRelay-PagerDuty-Migrator/1.0",
            },
            verify_tls=verify_tls,
            timeout=timeout,
            retries=retries,
        )

    def get(self, path: str, *, query: Mapping[str, Any] | None = None) -> Any:
        return self.http.request("GET", path, query=query)

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self.http.request("POST", path, body=body, expected=(200, 201, 202))

    def put(self, path: str, body: Mapping[str, Any]) -> Any:
        return self.http.request("PUT", path, body=body, expected=(200, 201))

    def list_groups(self) -> list[dict[str, Any]]:
        return dict_list(self.get("/api/groups"))

    def list_users(self) -> list[dict[str, Any]]:
        payload = self.get("/api/admin/users")
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return dict_list(payload["items"])
        return dict_list(payload)

    def list_teams(self) -> list[dict[str, Any]]:
        return dict_list(self.get("/api/teams", query={"include_inactive": 1}))

    def list_team_users(self, team_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get(f"/api/teams/{team_id}/users"))

    def list_group_users(self, group_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get(f"/api/groups/{group_id}/users"))

    def list_rotations(self, team_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get("/api/rotations", query={"team_id": team_id}))

    def list_rotation_layers(self, rotation_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get(f"/api/rotations/{rotation_id}/layers"))

    def list_layer_members(self, layer_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get(f"/api/rotations/layers/{layer_id}/members"))

    def list_layer_restrictions(self, layer_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get(f"/api/rotations/layers/{layer_id}/restrictions"))

    def list_rotation_overrides(self, rotation_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get(f"/api/rotations/{rotation_id}/overrides"))

    def list_policies(self, team_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get("/api/escalation-policies", query={"team_id": team_id}))

    def list_policy_rules(self, policy_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get(f"/api/escalation-policies/{policy_id}/rules"))

    def list_services(self, team_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get("/api/services", query={"team_id": team_id}))

    def list_routes(self, team_id: int) -> list[dict[str, Any]]:
        return dict_list(self.get("/api/routes", query={"team_id": team_id}))

    def list_maintenance(self, group_id: int) -> list[dict[str, Any]]:
        return dict_list(
            self.get(
                "/api/maintenance-windows",
                query={"group_id": group_id, "include_finished": 1},
            )
        )


class StateStore:
    """Resumable source-to-target ID mapping."""

    RESOURCE_NAMES = (
        "users",
        "teams",
        "rotations",
        "layers",
        "layer_members",
        "overrides",
        "policies",
        "policy_rules",
        "services",
        "routes",
        "maintenance",
    )

    def __init__(self, path: Path, *, persist: bool) -> None:
        self.path = path
        self.persist = persist
        self.data: dict[str, Any] = {
            "version": STATE_VERSION,
            "updated_at": None,
            "resources": {name: {} for name in self.RESOURCE_NAMES},
        }
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if loaded.get("version") != STATE_VERSION:
                raise MigrationError(
                    f"unsupported state version {loaded.get('version')}; expected {STATE_VERSION}"
                )
            self.data = loaded
            resources = self.data.setdefault("resources", {})
            for name in self.RESOURCE_NAMES:
                resources.setdefault(name, {})

    def get(self, resource: str, source_key: Any) -> Any:
        return self.data["resources"][resource].get(str(source_key))

    def set(self, resource: str, source_key: Any, target_id: Any) -> None:
        self.data["resources"][resource][str(source_key)] = target_id
        self.save()

    def save(self) -> None:
        if not self.persist:
            return
        self.data["updated_at"] = iso_z(datetime.now(timezone.utc))
        write_json_secure(self.path, self.data)


class SecretStore:
    """Generated route tokens, isolated from reports and stdout."""

    def __init__(self, path: Path, *, persist: bool) -> None:
        self.path = path
        self.persist = persist
        self.data: dict[str, Any] = {"version": 1, "routes": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            self.data.setdefault("routes", {})

    def set_route(self, source_service_id: str, payload: Mapping[str, Any]) -> None:
        self.data["routes"][str(source_service_id)] = dict(payload)
        if self.persist:
            write_json_secure(self.path, self.data)


@dataclass(slots=True)
class SourceSnapshot:
    users: list[dict[str, Any]]
    teams: list[dict[str, Any]]
    team_members: dict[str, list[dict[str, Any]]]
    schedules: list[dict[str, Any]]
    schedule_details: dict[str, dict[str, Any]]
    schedule_overrides: dict[str, list[dict[str, Any]]]
    policies: list[dict[str, Any]]
    services: list[dict[str, Any]]
    maintenance_windows: list[dict[str, Any]]
    v3_schedules: list[dict[str, Any]]

    def write(self, output_dir: Path) -> None:
        source = output_dir / "source"
        source.mkdir(parents=True, exist_ok=True)
        write_json(source / "users.json", self.users)
        write_json(source / "teams.json", self.teams)
        write_json(source / "team_members.json", self.team_members)
        write_json(source / "schedules.json", self.schedules)
        write_json(source / "schedule_details.json", self.schedule_details)
        write_json(source / "schedule_overrides.json", self.schedule_overrides)
        write_json(source / "escalation_policies.json", self.policies)
        write_json(source / "services.json", self.services)
        write_json(source / "maintenance_windows.json", self.maintenance_windows)
        write_json(source / "v3_schedules.json", self.v3_schedules)


@dataclass(slots=True)
class MigrationOptions:
    apply: bool
    group_id: int
    selected_stages: set[str]
    missing_users: str
    group_role: str
    team_role: str
    name_prefix: str
    fallback_team_name: str
    overrides_until_days: int
    create_routes: bool
    strict: bool


class Migrator:
    def __init__(
        self,
        pd: PagerDutyClient,
        ir: IncidentRelayClient,
        state: StateStore,
        secrets: SecretStore,
        reporter: Reporter,
        options: MigrationOptions,
    ) -> None:
        self.pd = pd
        self.ir = ir
        self.state = state
        self.secrets = secrets
        self.reporter = reporter
        self.options = options
        self._next_planned_id = -1

        self.snapshot: SourceSnapshot | None = None
        self.group: dict[str, Any] | None = None
        self.ir_users: list[dict[str, Any]] = []
        self.ir_teams: list[dict[str, Any]] = []
        self.ir_team_users: dict[int, list[dict[str, Any]]] = {}
        self.ir_group_users: list[dict[str, Any]] = []
        self.user_map: dict[str, int] = {}
        self.team_map: dict[str, int] = {}
        self.rotation_map: dict[tuple[str, int], int] = {}
        self.policy_map: dict[tuple[str, int], int] = {}
        self.service_map: dict[str, int] = {}
        self.service_team_map: dict[str, int] = {}
        self.fallback_team_id: int | None = None

        self.pd_users_by_id: dict[str, dict[str, Any]] = {}
        self.pd_teams_by_id: dict[str, dict[str, Any]] = {}
        self.pd_schedules_by_id: dict[str, dict[str, Any]] = {}
        self.pd_policies_by_id: dict[str, dict[str, Any]] = {}

        self.user_pd_teams: dict[str, set[str]] = defaultdict(set)
        self.schedule_pd_teams: dict[str, set[str]] = defaultdict(set)
        self.policy_pd_teams: dict[str, set[str]] = defaultdict(set)

    def planned_id(self) -> int:
        value = self._next_planned_id
        self._next_planned_id -= 1
        return value

    def selected(self, stage: str) -> bool:
        return stage in self.options.selected_stages

    def run(self, output_dir: Path) -> None:
        self.validate_target_group()
        self.snapshot = self.fetch_snapshot()
        self.snapshot.write(output_dir)
        self.index_source()
        self.load_target_inventory()

        if self.snapshot.v3_schedules:
            self.reporter.add(
                "warning",
                "v3_schedule",
                "unsupported",
                f"{len(self.snapshot.v3_schedules)} shift-based V3 schedules were snapshotted but not imported",
            )

        if self.selected("users") or any(
            self.selected(stage) for stage in ("teams", "schedules", "policies", "services", "maintenance")
        ):
            self.migrate_users()
        if self.selected("teams") or any(
            self.selected(stage) for stage in ("schedules", "policies", "services", "maintenance")
        ):
            self.migrate_teams()
        if self.selected("schedules") or self.selected("policies") or self.selected("services") or self.selected("maintenance"):
            self.migrate_schedules()
        if self.selected("policies") or self.selected("services") or self.selected("maintenance"):
            self.migrate_policies()
        if self.selected("services") or self.selected("maintenance"):
            self.migrate_services()
        if self.selected("maintenance"):
            self.migrate_maintenance_windows()

        self.reporter.add(
            "info",
            "history",
            "not_imported",
            "Incident and alert history is not imported by this version",
        )
        self.reporter.add(
            "info",
            "orchestration",
            "not_imported",
            "Event Orchestrations and Rulesets require manual conversion and are not imported",
        )

    def validate_target_group(self) -> None:
        groups = self.ir.list_groups()
        self.group = next(
            (item for item in groups if int_or_none(item.get("id")) == self.options.group_id),
            None,
        )
        if not self.group:
            raise MigrationError(
                f"IncidentRelay group {self.options.group_id} is not visible to the API token"
            )
        self.reporter.add(
            "info",
            "group",
            "target",
            f"using IncidentRelay group {self.group.get('name') or self.options.group_id}",
            self.options.group_id,
        )

    def fetch_snapshot(self) -> SourceSnapshot:
        self.reporter.add("info", "snapshot", "fetch", "reading PagerDuty configuration")
        users = self.pd.users()
        teams = self.pd.teams()
        team_members: dict[str, list[dict[str, Any]]] = {}
        for team in teams:
            team_id = str(team.get("id") or "")
            if not team_id:
                continue
            try:
                team_members[team_id] = self.pd.team_members(team_id)
            except ApiError as exc:
                self.reporter.add(
                    "warning",
                    "team_membership",
                    "snapshot_failed",
                    f"could not list PagerDuty team members: {exc}",
                    team_id,
                )
                team_members[team_id] = []

        schedules = self.pd.schedules()
        schedule_details: dict[str, dict[str, Any]] = {}
        schedule_overrides: dict[str, list[dict[str, Any]]] = {}
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=self.options.overrides_until_days)
        for schedule in schedules:
            schedule_id = str(schedule.get("id") or "")
            if not schedule_id:
                continue
            try:
                schedule_details[schedule_id] = self.pd.schedule(schedule_id)
            except ApiError as exc:
                self.reporter.add(
                    "warning",
                    "schedule",
                    "snapshot_failed",
                    f"could not read schedule details: {exc}",
                    schedule_id,
                )
                schedule_details[schedule_id] = schedule
            try:
                schedule_overrides[schedule_id] = self.pd.schedule_overrides(
                    schedule_id, now, until
                )
            except ApiError as exc:
                self.reporter.add(
                    "warning",
                    "override",
                    "snapshot_failed",
                    f"could not read future overrides: {exc}",
                    schedule_id,
                )
                schedule_overrides[schedule_id] = []

        policies = []
        for summary in self.pd.escalation_policies():
            policy_id = str(summary.get("id") or "")
            if not policy_id:
                continue
            if summary.get("escalation_rules"):
                policies.append(summary)
                continue
            try:
                policies.append(self.pd.escalation_policy(policy_id))
            except ApiError as exc:
                self.reporter.add(
                    "warning",
                    "policy",
                    "snapshot_failed",
                    f"could not read policy details: {exc}",
                    policy_id,
                )
                policies.append(summary)

        services = self.pd.services()
        maintenance = self.pd.maintenance_windows()
        v3_schedules = self.pd.v3_schedules()
        self.reporter.add(
            "info",
            "snapshot",
            "complete",
            "PagerDuty snapshot completed",
            users=len(users),
            teams=len(teams),
            schedules=len(schedules),
            policies=len(policies),
            services=len(services),
            maintenance_windows=len(maintenance),
            v3_schedules=len(v3_schedules),
        )
        return SourceSnapshot(
            users=users,
            teams=teams,
            team_members=team_members,
            schedules=schedules,
            schedule_details=schedule_details,
            schedule_overrides=schedule_overrides,
            policies=policies,
            services=services,
            maintenance_windows=maintenance,
            v3_schedules=v3_schedules,
        )

    def index_source(self) -> None:
        assert self.snapshot is not None
        self.pd_users_by_id = by_id(self.snapshot.users)
        self.pd_teams_by_id = by_id(self.snapshot.teams)
        self.pd_schedules_by_id = {
            source_id: detail
            for source_id, detail in self.snapshot.schedule_details.items()
        }
        self.pd_policies_by_id = by_id(self.snapshot.policies)

        for team_id, members in self.snapshot.team_members.items():
            for member in members:
                user = member.get("user") if isinstance(member.get("user"), dict) else member
                user_id = str(user.get("id") or member.get("user_id") or "")
                if user_id:
                    self.user_pd_teams[user_id].add(team_id)

        for schedule_id, schedule in self.pd_schedules_by_id.items():
            for team in as_list(schedule.get("teams")):
                team_id = object_id(team)
                if team_id:
                    self.schedule_pd_teams[schedule_id].add(team_id)

        for policy in self.snapshot.policies:
            policy_id = str(policy.get("id") or "")
            teams = {object_id(item) for item in as_list(policy.get("teams"))}
            teams.discard("")
            self.policy_pd_teams[policy_id].update(teams)
            for rule in as_list(policy.get("escalation_rules")):
                for target in as_list(rule.get("targets")):
                    if str(target.get("type") or "").lower().startswith("schedule"):
                        schedule_id = object_id(target)
                        if schedule_id:
                            self.schedule_pd_teams[schedule_id].update(teams)

        for service in self.snapshot.services:
            policy_id = object_id(service.get("escalation_policy"))
            service_teams = {object_id(item) for item in as_list(service.get("teams"))}
            service_teams.discard("")
            if policy_id:
                self.policy_pd_teams[policy_id].update(service_teams)

    def load_target_inventory(self) -> None:
        self.ir_users = self.ir.list_users()
        self.ir_teams = self.ir.list_teams()
        self.ir_group_users = self.ir.list_group_users(self.options.group_id)
        self.reporter.add(
            "info",
            "inventory",
            "loaded",
            "IncidentRelay target inventory loaded",
            users=len(self.ir_users),
            teams=len(self.ir_teams),
        )

    def migrate_users(self) -> None:
        assert self.snapshot is not None
        existing_by_email = {
            normalize_email(item.get("email")): item
            for item in self.ir_users
            if normalize_email(item.get("email"))
        }
        existing_by_username = {
            str(item.get("username") or "").lower(): item
            for item in self.ir_users
            if item.get("username")
        }

        for user in self.snapshot.users:
            source_id = str(user.get("id") or "")
            if not source_id:
                continue
            mapped = int_or_none(self.state.get("users", source_id))
            if mapped:
                self.user_map[source_id] = mapped
                self.ensure_group_membership(mapped)
                continue

            email = normalize_email(user.get("email"))
            existing = existing_by_email.get(email) if email else None
            if existing:
                target_id = int(existing["id"])
                self.user_map[source_id] = target_id
                self.state.set("users", source_id, target_id)
                self.reporter.add(
                    "info", "user", "adopt", "matched existing user by email", source_id,
                    email=email, incidentrelay_id=target_id,
                )
                self.ensure_group_membership(target_id)
                continue

            if self.options.missing_users == "skip":
                self.reporter.add(
                    "warning",
                    "user",
                    "skip",
                    "no IncidentRelay user with matching email; dependent schedule targets may be skipped",
                    source_id,
                    email=email,
                )
                continue

            username = unique_username(user, existing_by_username)
            payload = {
                "username": username,
                "display_name": truncate(user.get("name") or username, 120),
                "email": email or None,
                "active": self.options.missing_users == "create-active",
                "is_admin": False,
                "group_id": self.options.group_id,
                "group_role": self.options.group_role,
            }
            target = self.create_or_plan("user", source_id, "/api/admin/users", payload)
            target_id = int(target.get("id") or self.planned_id())
            self.user_map[source_id] = target_id
            self.state.set("users", source_id, target_id)
            target_record = {"id": target_id, **payload}
            self.ir_users.append(target_record)
            self.ir_group_users.append({
                "user_id": target_id,
                "role": self.options.group_role,
                "active": True,
            })
            if email:
                existing_by_email[email] = target_record
            existing_by_username[username.lower()] = target_record

    def ensure_group_membership(self, user_id: int) -> None:
        if any(int_or_none(item.get("user_id")) == user_id for item in self.ir_group_users):
            return
        payload = {"user_id": user_id, "role": self.options.group_role, "active": True}
        if self.options.apply:
            try:
                self.ir.post(f"/api/groups/{self.options.group_id}/users", payload)
            except ApiError as exc:
                if exc.status != 409:
                    raise
        self.ir_group_users.append(payload)
        self.reporter.add(
            "info",
            "group_membership",
            "create" if self.options.apply else "plan",
            "added user to target group",
            user_id,
            group_id=self.options.group_id,
        )

    def migrate_teams(self) -> None:
        assert self.snapshot is not None
        existing = [
            item
            for item in self.ir_teams
            if int_or_none(item.get("group_id") or nested_id(item.get("group")))
            == self.options.group_id
        ]
        by_slug = {str(item.get("slug") or "").lower(): item for item in existing}
        by_name = {str(item.get("name") or "").lower(): item for item in existing}

        for team in self.snapshot.teams:
            source_id = str(team.get("id") or "")
            if not source_id:
                continue
            mapped = int_or_none(self.state.get("teams", source_id))
            if mapped:
                self.team_map[source_id] = mapped
                self.migrate_team_memberships(source_id, mapped)
                continue

            name = prefixed_name(self.options.name_prefix, team.get("name") or f"Team {source_id}", 120)
            slug = unique_slug(name, set(by_slug), suffix=source_id)
            found = by_slug.get(slug) or by_name.get(name.lower())
            if found:
                target_id = int(found["id"])
                self.team_map[source_id] = target_id
                self.state.set("teams", source_id, target_id)
                self.reporter.add(
                    "info", "team", "adopt", "matched existing team", source_id,
                    incidentrelay_id=target_id,
                )
            else:
                payload = {
                    "group_id": self.options.group_id,
                    "slug": slug,
                    "name": name,
                    "description": truncate(
                        team.get("description") or f"Imported from PagerDuty team {source_id}",
                        2048,
                    ),
                    "escalation_enabled": True,
                    "escalation_after_reminders": 2,
                    "active": True,
                }
                target = self.create_or_plan("team", source_id, "/api/teams", payload)
                target_id = int(target.get("id") or self.planned_id())
                self.team_map[source_id] = target_id
                self.state.set("teams", source_id, target_id)
                record = {"id": target_id, **payload}
                self.ir_teams.append(record)
                by_slug[slug] = record
                by_name[name.lower()] = record

            self.migrate_team_memberships(source_id, self.team_map[source_id])


    def ensure_fallback_team(
        self,
        by_slug: dict[str, dict[str, Any]],
        by_name: dict[str, dict[str, Any]],
    ) -> int:
        key = "__fallback__"
        mapped = int_or_none(self.state.get("teams", key))
        if mapped:
            return mapped
        name = prefixed_name(
            self.options.name_prefix,
            self.options.fallback_team_name,
            120,
        )
        found = by_name.get(name.lower())
        if found:
            target_id = int(found["id"])
            self.state.set("teams", key, target_id)
            return target_id
        slug = unique_slug(name, set(by_slug), suffix="fallback")
        payload = {
            "group_id": self.options.group_id,
            "slug": slug,
            "name": name,
            "description": "Fallback team for PagerDuty resources without an explicit team",
            "escalation_enabled": True,
            "escalation_after_reminders": 2,
            "active": True,
        }
        target = self.create_or_plan("team", key, "/api/teams", payload)
        target_id = int(target.get("id") or self.planned_id())
        self.state.set("teams", key, target_id)
        self.ir_teams.append({"id": target_id, **payload})
        return target_id

    def migrate_team_memberships(self, pd_team_id: str, ir_team_id: int) -> None:
        assert self.snapshot is not None
        members = self.snapshot.team_members.get(pd_team_id, [])
        existing = self.ir_team_users.get(ir_team_id)
        if existing is None:
            existing = self.ir.list_team_users(ir_team_id) if self.options.apply or ir_team_id > 0 else []
            self.ir_team_users[ir_team_id] = existing
        existing_user_ids = {int_or_none(item.get("user_id")) for item in existing}

        for member in members:
            source_user = member.get("user") if isinstance(member.get("user"), dict) else member
            pd_user_id = str(source_user.get("id") or member.get("user_id") or "")
            ir_user_id = self.user_map.get(pd_user_id)
            if not ir_user_id:
                self.reporter.add(
                    "warning", "team_membership", "skip", "PagerDuty user is not mapped", pd_user_id,
                    pagerduty_team_id=pd_team_id,
                )
                continue
            self.ensure_group_membership(ir_user_id)
            if ir_user_id in existing_user_ids:
                continue
            pd_role = str(member.get("role") or "").lower()
            role = "manager" if pd_role in {"manager", "owner"} else self.options.team_role
            payload = {"user_id": ir_user_id, "role": role, "active": True}
            if self.options.apply:
                try:
                    self.ir.post(f"/api/teams/{ir_team_id}/users", payload)
                except ApiError as exc:
                    if exc.status != 409:
                        raise
            existing.append(payload)
            existing_user_ids.add(ir_user_id)
            self.reporter.add(
                "info",
                "team_membership",
                "create" if self.options.apply else "plan",
                "added user to team",
                pd_user_id,
                incidentrelay_team_id=ir_team_id,
                role=role,
            )

    def target_teams_for_pd_ids(self, pd_team_ids: Iterable[str]) -> list[int]:
        result = [self.team_map[item] for item in pd_team_ids if item in self.team_map]
        return unique_ints(result) or [self.require_fallback_team()]

    def require_fallback_team(self) -> int:
        if self.fallback_team_id is None:
            existing = [
                item
                for item in self.ir_teams
                if int_or_none(item.get("group_id") or nested_id(item.get("group")))
                == self.options.group_id
            ]
            by_slug = {str(item.get("slug") or "").lower(): item for item in existing}
            by_name = {str(item.get("name") or "").lower(): item for item in existing}
            self.fallback_team_id = self.ensure_fallback_team(by_slug, by_name)
        return self.fallback_team_id

    def migrate_schedules(self) -> None:
        assert self.snapshot is not None
        for schedule_id, schedule in self.pd_schedules_by_id.items():
            layers = as_list(schedule.get("schedule_layers"))
            if not layers:
                self.reporter.add(
                    "warning", "schedule", "skip", "schedule has no legacy schedule_layers", schedule_id,
                )
                continue
            pd_team_ids = self.schedule_pd_teams.get(schedule_id, set())
            target_team_ids = self.target_teams_for_pd_ids(pd_team_ids)
            if len(target_team_ids) > 1:
                self.reporter.add(
                    "warning",
                    "schedule",
                    "clone",
                    "schedule is shared by multiple teams and will be cloned in IncidentRelay",
                    schedule_id,
                    copies=len(target_team_ids),
                )
            for team_id in target_team_ids:
                self.ensure_schedule_clone(schedule_id, schedule, team_id)

    def ensure_schedule_clone(
        self,
        schedule_id: str,
        schedule: Mapping[str, Any],
        team_id: int,
    ) -> int:
        map_key = f"{schedule_id}:{team_id}"
        mapped = int_or_none(self.state.get("rotations", map_key))
        if mapped:
            self.rotation_map[(schedule_id, team_id)] = mapped
            self.ensure_schedule_users_in_team(schedule, team_id)
            self.ensure_schedule_layers(schedule_id, schedule, team_id, mapped)
            self.ensure_schedule_overrides(schedule_id, team_id, mapped)
            return mapped

        name = prefixed_name(
            self.options.name_prefix,
            schedule.get("name") or f"Schedule {schedule_id}",
            120,
        )
        rotations = self.ir.list_rotations(team_id) if self.options.apply or team_id > 0 else []
        found = next((item for item in rotations if str(item.get("name")) == name), None)
        if found:
            rotation_id = int(found["id"])
            self.reporter.add(
                "info", "rotation", "adopt", "matched existing rotation by name", schedule_id,
                incidentrelay_id=rotation_id, team_id=team_id,
            )
        else:
            first_layer = as_list(schedule.get("schedule_layers"))[0]
            schedule_fields = rotation_fields(first_layer, schedule.get("time_zone") or "UTC")
            payload = {
                "team_id": team_id,
                "name": name,
                "description": truncate(
                    schedule.get("description") or f"Imported from PagerDuty schedule {schedule_id}",
                    2048,
                ),
                **schedule_fields,
                "reminder_interval_seconds": 300,
                "add_team_members": False,
                "enabled": True,
            }
            target = self.create_or_plan("rotation", map_key, "/api/rotations", payload)
            rotation_id = int(target.get("id") or self.planned_id())
        self.rotation_map[(schedule_id, team_id)] = rotation_id
        self.state.set("rotations", map_key, rotation_id)

        self.ensure_schedule_users_in_team(schedule, team_id)
        self.ensure_schedule_layers(schedule_id, schedule, team_id, rotation_id)
        self.ensure_schedule_overrides(schedule_id, team_id, rotation_id)
        return rotation_id

    def ensure_schedule_users_in_team(self, schedule: Mapping[str, Any], team_id: int) -> None:
        existing = self.ir_team_users.get(team_id)
        if existing is None:
            existing = self.ir.list_team_users(team_id) if self.options.apply or team_id > 0 else []
            self.ir_team_users[team_id] = existing
        existing_ids = {int_or_none(item.get("user_id")) for item in existing}
        for layer in as_list(schedule.get("schedule_layers")):
            for entry in as_list(layer.get("users")):
                user = entry.get("user") if isinstance(entry.get("user"), dict) else entry
                pd_user_id = str(user.get("id") or "")
                ir_user_id = self.user_map.get(pd_user_id)
                if not ir_user_id or ir_user_id in existing_ids:
                    continue
                self.ensure_group_membership(ir_user_id)
                payload = {"user_id": ir_user_id, "role": self.options.team_role, "active": True}
                if self.options.apply:
                    try:
                        self.ir.post(f"/api/teams/{team_id}/users", payload)
                    except ApiError as exc:
                        if exc.status != 409:
                            raise
                existing.append(payload)
                existing_ids.add(ir_user_id)
                self.reporter.add(
                    "info", "team_membership", "create" if self.options.apply else "plan",
                    "added schedule participant to team", pd_user_id, incidentrelay_team_id=team_id,
                )

    def ensure_schedule_layers(
        self,
        schedule_id: str,
        schedule: Mapping[str, Any],
        team_id: int,
        rotation_id: int,
    ) -> None:
        existing_layers = (
            self.ir.list_rotation_layers(rotation_id)
            if self.options.apply or rotation_id > 0
            else []
        )
        by_name = {str(item.get("name") or ""): item for item in existing_layers}
        timezone_name = str(schedule.get("time_zone") or "UTC")

        for index, layer in enumerate(as_list(schedule.get("schedule_layers"))):
            source_layer_id = str(layer.get("id") or index)
            map_key = f"{schedule_id}:{source_layer_id}:{team_id}"
            mapped = int_or_none(self.state.get("layers", map_key))
            layer_name = truncate(layer.get("name") or f"Layer {index + 1}", 120)
            if mapped:
                layer_id = mapped
            elif layer_name in by_name:
                layer_id = int(by_name[layer_name]["id"])
                self.state.set("layers", map_key, layer_id)
                self.reporter.add(
                    "info", "rotation_layer", "adopt", "matched existing layer by name", source_layer_id,
                    rotation_id=rotation_id,
                )
            else:
                payload = {
                    "name": layer_name,
                    "description": truncate(
                        f"Imported from PagerDuty schedule {schedule_id}, layer {source_layer_id}",
                        2048,
                    ),
                    "priority": index,
                    **rotation_fields(layer, timezone_name),
                    "enabled": True,
                }
                target = self.create_or_plan(
                    "rotation_layer",
                    map_key,
                    f"/api/rotations/{rotation_id}/layers",
                    payload,
                )
                layer_id = int(target.get("id") or self.planned_id())
                self.state.set("layers", map_key, layer_id)

            self.ensure_layer_members(schedule_id, source_layer_id, layer, layer_id)
            self.ensure_layer_restrictions(schedule_id, source_layer_id, layer, layer_id)

    def ensure_layer_members(
        self,
        schedule_id: str,
        source_layer_id: str,
        layer: Mapping[str, Any],
        layer_id: int,
    ) -> None:
        existing = self.ir.list_layer_members(layer_id) if self.options.apply or layer_id > 0 else []
        existing_user_ids = {int_or_none(item.get("user_id")) for item in existing}
        for position, entry in enumerate(as_list(layer.get("users"))):
            user = entry.get("user") if isinstance(entry.get("user"), dict) else entry
            pd_user_id = str(user.get("id") or "")
            ir_user_id = self.user_map.get(pd_user_id)
            if not ir_user_id:
                self.reporter.add(
                    "warning", "rotation_layer_member", "skip", "PagerDuty user is not mapped", pd_user_id,
                    schedule_id=schedule_id,
                )
                continue
            member_key = f"{schedule_id}:{source_layer_id}:{pd_user_id}:{layer_id}"
            if self.state.get("layer_members", member_key) or ir_user_id in existing_user_ids:
                continue
            payload = {"user_id": ir_user_id, "position": position, "starts_at": None}
            target = self.create_or_plan(
                "rotation_layer_member",
                member_key,
                f"/api/rotations/layers/{layer_id}/members",
                payload,
            )
            target_id = target.get("id") or self.planned_id()
            self.state.set("layer_members", member_key, target_id)
            existing_user_ids.add(ir_user_id)

    def ensure_layer_restrictions(
        self,
        schedule_id: str,
        source_layer_id: str,
        layer: Mapping[str, Any],
        layer_id: int,
    ) -> None:
        restrictions, warnings = convert_restrictions(as_list(layer.get("restrictions")))
        for warning in warnings:
            self.reporter.add(
                "warning", "rotation_restriction", "degraded", warning, source_layer_id,
                schedule_id=schedule_id,
            )
        if not restrictions:
            return
        state_key = f"{schedule_id}:{source_layer_id}:{layer_id}"
        if self.state.get("layers", f"restrictions:{state_key}"):
            return
        if self.options.apply:
            existing = self.ir.list_layer_restrictions(layer_id)
            if restriction_signatures(existing) != restriction_signatures(restrictions):
                self.ir.put(
                    f"/api/rotations/layers/{layer_id}/restrictions",
                    {"restrictions": restrictions},
                )
        self.state.set("layers", f"restrictions:{state_key}", True)
        self.reporter.add(
            "info",
            "rotation_restriction",
            "replace" if self.options.apply else "plan",
            f"configured {len(restrictions)} layer restrictions",
            source_layer_id,
        )

    def ensure_schedule_overrides(self, schedule_id: str, team_id: int, rotation_id: int) -> None:
        assert self.snapshot is not None
        existing = self.ir.list_rotation_overrides(rotation_id) if self.options.apply or rotation_id > 0 else []
        existing_signatures = {
            (
                int_or_none(item.get("user_id")),
                normalize_iso(item.get("starts_at")),
                normalize_iso(item.get("ends_at")),
            )
            for item in existing
        }
        now = datetime.now(timezone.utc)
        for override in self.snapshot.schedule_overrides.get(schedule_id, []):
            source_id = str(override.get("id") or stable_hash(override))
            state_key = f"{schedule_id}:{source_id}:{team_id}"
            if self.state.get("overrides", state_key):
                continue
            user = override.get("user") if isinstance(override.get("user"), dict) else {}
            pd_user_id = str(user.get("id") or override.get("user_id") or "")
            ir_user_id = self.user_map.get(pd_user_id)
            starts = parse_datetime(override.get("start") or override.get("start_time"))
            ends = parse_datetime(override.get("end") or override.get("end_time"))
            if not ir_user_id or not starts or not ends or ends <= now:
                self.reporter.add(
                    "warning", "override", "skip", "override is invalid, expired, or has an unmapped user", source_id,
                    schedule_id=schedule_id,
                )
                continue
            signature = (ir_user_id, iso_z(starts), iso_z(ends))
            if signature in existing_signatures:
                self.state.set("overrides", state_key, True)
                continue
            payload = {
                "user_id": ir_user_id,
                "starts_at": iso_z(starts),
                "ends_at": iso_z(ends),
                "reason": truncate(
                    override.get("summary") or f"Imported from PagerDuty override {source_id}",
                    2048,
                ),
            }
            target = self.create_or_plan(
                "override",
                state_key,
                f"/api/rotations/{rotation_id}/overrides",
                payload,
            )
            self.state.set("overrides", state_key, target.get("id") or True)
            existing_signatures.add(signature)

    def migrate_policies(self) -> None:
        assert self.snapshot is not None
        for policy in self.snapshot.policies:
            policy_id = str(policy.get("id") or "")
            if not policy_id:
                continue
            pd_team_ids = self.policy_pd_teams.get(policy_id, set())
            target_team_ids = self.target_teams_for_pd_ids(pd_team_ids)
            if len(target_team_ids) > 1:
                self.reporter.add(
                    "warning", "policy", "clone", "policy is shared by teams and will be cloned", policy_id,
                    copies=len(target_team_ids),
                )
            for team_id in target_team_ids:
                self.ensure_policy_clone(policy_id, policy, team_id)

    def ensure_policy_clone(
        self,
        policy_id: str,
        policy: Mapping[str, Any],
        team_id: int,
    ) -> int:
        map_key = f"{policy_id}:{team_id}"
        mapped = int_or_none(self.state.get("policies", map_key))
        if mapped:
            self.policy_map[(policy_id, team_id)] = mapped
            self.ensure_policy_rules(policy_id, policy, team_id, mapped)
            return mapped
        name = prefixed_name(
            self.options.name_prefix,
            policy.get("name") or f"Policy {policy_id}",
            120,
        )
        existing = self.ir.list_policies(team_id) if self.options.apply or team_id > 0 else []
        found = next((item for item in existing if str(item.get("name")) == name), None)
        if found:
            ir_policy_id = int(found["id"])
            self.reporter.add(
                "info", "policy", "adopt", "matched existing policy by name", policy_id,
                incidentrelay_id=ir_policy_id,
            )
        else:
            repeat_count = min(max(int(policy.get("num_loops") or 0), 0), 50)
            payload = {
                "team_id": team_id,
                "name": name,
                "description": truncate(
                    policy.get("description") or f"Imported from PagerDuty policy {policy_id}",
                    2048,
                ),
                "enabled": True,
                "repeat_count": repeat_count,
            }
            target = self.create_or_plan("policy", map_key, "/api/escalation-policies", payload)
            ir_policy_id = int(target.get("id") or self.planned_id())
        self.policy_map[(policy_id, team_id)] = ir_policy_id
        self.state.set("policies", map_key, ir_policy_id)
        self.ensure_policy_rules(policy_id, policy, team_id, ir_policy_id)
        return ir_policy_id

    def ensure_policy_rules(
        self,
        policy_id: str,
        policy: Mapping[str, Any],
        team_id: int,
        ir_policy_id: int,
    ) -> None:
        existing = self.ir.list_policy_rules(ir_policy_id) if self.options.apply or ir_policy_id > 0 else []
        signatures = {
            (
                int_or_none(item.get("position")),
                int_or_none(item.get("delay_seconds")),
                str(item.get("target_type") or ""),
                int_or_none(item.get("target_id")),
            )
            for item in existing
        }
        position = 1
        for rule_index, rule in enumerate(as_list(policy.get("escalation_rules"))):
            targets = [item for item in as_list(rule.get("targets")) if isinstance(item, dict)]
            if len(targets) > 1:
                self.reporter.add(
                    "warning",
                    "policy_rule",
                    "degraded",
                    "parallel PagerDuty targets are converted to consecutive IncidentRelay rules; additional targets have zero delay",
                    f"{policy_id}:{rule_index}",
                    target_count=len(targets),
                )
            base_delay = min(max(int(rule.get("escalation_delay_in_minutes") or 0) * 60, 0), 86400)
            for target_index, target in enumerate(targets):
                if position > 100:
                    self.reporter.add(
                        "warning", "policy_rule", "skip", "IncidentRelay policy rule limit (100) reached", policy_id,
                    )
                    return
                target_type, target_id = self.resolve_policy_target(target, team_id)
                if not target_type or not target_id:
                    self.reporter.add(
                        "warning", "policy_rule", "skip", "target could not be mapped", object_id(target),
                        policy_id=policy_id,
                    )
                    continue
                delay = base_delay if target_index == 0 else 0
                signature = (position, delay, target_type, target_id)
                state_key = f"{policy_id}:{team_id}:{rule_index}:{target_index}"
                if self.state.get("policy_rules", state_key) or signature in signatures:
                    position += 1
                    continue
                payload = {
                    "position": position,
                    "delay_seconds": delay,
                    "target_type": target_type,
                    "target_id": target_id,
                    "enabled": True,
                }
                target_record = self.create_or_plan(
                    "policy_rule",
                    state_key,
                    f"/api/escalation-policies/{ir_policy_id}/rules",
                    payload,
                )
                self.state.set("policy_rules", state_key, target_record.get("id") or True)
                signatures.add(signature)
                position += 1

    def resolve_policy_target(
        self,
        target: Mapping[str, Any],
        team_id: int,
    ) -> tuple[str | None, int | None]:
        target_type = str(target.get("type") or "").lower()
        source_id = object_id(target)
        if target_type.startswith("user"):
            ir_user_id = self.user_map.get(source_id)
            if ir_user_id:
                self.ensure_user_in_team(ir_user_id, team_id)
                return "user", ir_user_id
            return None, None
        if target_type.startswith("schedule"):
            schedule = self.pd_schedules_by_id.get(source_id)
            if not schedule:
                return None, None
            rotation_id = self.rotation_map.get((source_id, team_id))
            if not rotation_id:
                rotation_id = self.ensure_schedule_clone(source_id, schedule, team_id)
            return "rotation", rotation_id
        return None, None

    def ensure_user_in_team(self, user_id: int, team_id: int) -> None:
        existing = self.ir_team_users.get(team_id)
        if existing is None:
            existing = self.ir.list_team_users(team_id) if self.options.apply or team_id > 0 else []
            self.ir_team_users[team_id] = existing
        if any(int_or_none(item.get("user_id")) == user_id for item in existing):
            return
        self.ensure_group_membership(user_id)
        payload = {"user_id": user_id, "role": self.options.team_role, "active": True}
        if self.options.apply:
            try:
                self.ir.post(f"/api/teams/{team_id}/users", payload)
            except ApiError as exc:
                if exc.status != 409:
                    raise
        existing.append(payload)
        self.reporter.add(
            "info", "team_membership", "create" if self.options.apply else "plan",
            "added escalation target user to team", user_id, incidentrelay_team_id=team_id,
        )

    def migrate_services(self) -> None:
        assert self.snapshot is not None
        for service in self.snapshot.services:
            source_id = str(service.get("id") or "")
            if not source_id:
                continue
            pd_team_ids = [object_id(item) for item in as_list(service.get("teams"))]
            pd_team_ids = [item for item in pd_team_ids if item]
            policy_id = object_id(service.get("escalation_policy"))
            if not pd_team_ids and policy_id:
                pd_team_ids = sorted(self.policy_pd_teams.get(policy_id, set()))
            target_teams = self.target_teams_for_pd_ids(pd_team_ids)
            team_id = target_teams[0]
            if len(target_teams) > 1:
                self.reporter.add(
                    "warning", "service", "degraded", "PagerDuty service has multiple teams; first mapped team selected", source_id,
                    incidentrelay_team_id=team_id,
                )
            self.ensure_service(source_id, service, team_id, policy_id)

    def ensure_service(
        self,
        source_id: str,
        service: Mapping[str, Any],
        team_id: int,
        policy_id: str,
    ) -> int:
        mapped = int_or_none(self.state.get("services", source_id))
        if mapped:
            self.service_map[source_id] = mapped
            self.service_team_map[source_id] = team_id
            ir_policy_id = self.policy_map.get((policy_id, team_id)) if policy_id else None
            if self.options.create_routes and self.selected("services"):
                self.ensure_service_route(source_id, service, team_id, mapped, ir_policy_id)
            return mapped
        name = prefixed_name(
            self.options.name_prefix,
            service.get("name") or f"Service {source_id}",
            120,
        )
        services = self.ir.list_services(team_id) if self.options.apply or team_id > 0 else []
        used_slugs = {str(item.get("slug") or "") for item in services}
        slug = unique_slug(name, used_slugs, suffix=source_id)
        found = next(
            (
                item
                for item in services
                if str(item.get("slug")) == slug or str(item.get("name")) == name
            ),
            None,
        )
        ir_policy_id = self.policy_map.get((policy_id, team_id)) if policy_id else None
        if policy_id and not ir_policy_id and policy_id in self.pd_policies_by_id:
            ir_policy_id = self.ensure_policy_clone(
                policy_id,
                self.pd_policies_by_id[policy_id],
                team_id,
            )
        if found:
            service_id = int(found["id"])
            self.reporter.add(
                "info", "service", "adopt", "matched existing service", source_id,
                incidentrelay_id=service_id,
            )
        else:
            payload = {
                "team_id": team_id,
                "slug": slug,
                "name": name,
                "description": truncate(
                    service.get("description") or f"Imported from PagerDuty service {source_id}",
                    2048,
                ),
                "service_type": "other",
                "environment": "production",
                "criticality": "medium",
                "tier": "tier_3",
                "status": "operational",
                "status_source": "manual",
                "status_message": None,
                "default_rotation_id": None,
                "default_escalation_policy_id": ir_policy_id,
                "notification_policy_id": None,
                "priority_policy_id": None,
                "labels": {"source": "pagerduty", "pagerduty_service_id": source_id},
                "tags": ["pagerduty-import"],
                "metadata": {
                    "pagerduty": {
                        "id": source_id,
                        "html_url": service.get("html_url"),
                        "status": service.get("status"),
                        "escalation_policy_id": policy_id or None,
                    }
                },
                "enabled": str(service.get("status") or "active").lower() != "disabled",
                "public": False,
                "public_name": None,
                "public_description": None,
                "public_order": 100,
                "kind": "technical",
                "lifecycle": "production",
            }
            target = self.create_or_plan("service", source_id, "/api/services", payload)
            service_id = int(target.get("id") or self.planned_id())
        self.service_map[source_id] = service_id
        self.service_team_map[source_id] = team_id
        self.state.set("services", source_id, service_id)
        if self.options.create_routes and self.selected("services"):
            self.ensure_service_route(source_id, service, team_id, service_id, ir_policy_id)
        return service_id

    def ensure_service_route(
        self,
        source_id: str,
        service: Mapping[str, Any],
        team_id: int,
        service_id: int,
        policy_id: int | None,
    ) -> None:
        mapped = int_or_none(self.state.get("routes", source_id))
        if mapped:
            return
        name = prefixed_name(
            self.options.name_prefix,
            f"PagerDuty Events API v2 — {service.get('name') or source_id}",
            120,
        )
        existing = self.ir.list_routes(team_id) if self.options.apply or team_id > 0 else []
        found = next((item for item in existing if str(item.get("name")) == name), None)
        if found:
            route_id = int(found["id"])
            self.state.set("routes", source_id, route_id)
            self.reporter.add(
                "warning",
                "route",
                "adopt",
                "matched existing route; intake token cannot be recovered and is not written to secrets file",
                source_id,
                incidentrelay_id=route_id,
            )
            return
        payload = {
            "team_id": team_id,
            "name": name,
            "source": "webhook",
            "rotation_id": None,
            "channel_ids": [],
            "notification_channel_mode": "route_only",
            "matcher_preset_id": None,
            "matchers": {},
            "group_by": [],
            "integration_config": {
                "pagerduty": {
                    "compatible_events_api_v2": True,
                    "source_service_id": source_id,
                }
            },
            "enabled": True,
            "escalation_mode": "policy" if policy_id else "rotation",
            "escalation_policy_id": policy_id,
            "service_id": service_id,
        }
        target = self.create_or_plan("route", source_id, "/api/routes", payload)
        route_id = int(target.get("id") or self.planned_id())
        self.state.set("routes", source_id, route_id)
        intake_token = target.get("intake_token")
        if self.options.apply and intake_token:
            self.secrets.set_route(
                source_id,
                {
                    "pagerduty_service_id": source_id,
                    "pagerduty_service_name": service.get("name"),
                    "incidentrelay_route_id": route_id,
                    "endpoint": f"{self.ir.base_url}/api/integrations/webhook",
                    "routing_key": intake_token,
                },
            )
            self.reporter.add(
                "info",
                "route",
                "secret_saved",
                "generated intake token saved to the protected route secrets file",
                source_id,
                incidentrelay_id=route_id,
            )

    def migrate_maintenance_windows(self) -> None:
        assert self.snapshot is not None
        existing = self.ir.list_maintenance(self.options.group_id)
        existing_names = {str(item.get("name") or "") for item in existing}
        now = datetime.now(timezone.utc)
        for window in self.snapshot.maintenance_windows:
            source_id = str(window.get("id") or "")
            if not source_id:
                continue
            if self.state.get("maintenance", source_id):
                continue
            starts = parse_datetime(window.get("start_time") or window.get("starts_at"))
            ends = parse_datetime(window.get("end_time") or window.get("ends_at"))
            if not starts or not ends or ends <= now:
                self.reporter.add(
                    "info", "maintenance", "skip", "maintenance window is expired or has invalid times", source_id,
                )
                continue
            scopes: list[dict[str, Any]] = []
            for service_ref in as_list(window.get("services")):
                pd_service_id = object_id(service_ref)
                ir_service_id = self.service_map.get(pd_service_id)
                if ir_service_id:
                    scopes.append({"scope_type": "service", "service_id": ir_service_id})
            if not scopes:
                for team_ref in as_list(window.get("teams")):
                    pd_team_id = object_id(team_ref)
                    ir_team_id = self.team_map.get(pd_team_id)
                    if ir_team_id:
                        scopes.append({"scope_type": "team", "team_id": ir_team_id})
            if not scopes:
                scopes = [{"scope_type": "group", "group_id": self.options.group_id}]
                self.reporter.add(
                    "warning", "maintenance", "degraded", "no mapped services/teams; group scope used", source_id,
                )
            name = prefixed_name(
                self.options.name_prefix,
                window.get("summary") or f"Maintenance {source_id}",
                255,
            )
            if name in existing_names:
                self.state.set("maintenance", source_id, True)
                self.reporter.add(
                    "info", "maintenance", "adopt", "matched existing window by name", source_id,
                )
                continue
            payload = {
                "name": name,
                "description": truncate(
                    window.get("description") or f"Imported from PagerDuty maintenance window {source_id}",
                    2000,
                ),
                "behavior": "suppress_notifications",
                "timezone": "UTC",
                "rrule": None,
                "starts_at": iso_z(starts),
                "ends_at": iso_z(ends),
                "enabled": True,
                "scopes": dedupe_dicts(scopes),
            }
            target = self.create_or_plan(
                "maintenance", source_id, "/api/maintenance-windows", payload,
            )
            self.state.set("maintenance", source_id, target.get("id") or True)
            existing_names.add(name)

    def create_or_plan(
        self,
        entity: str,
        source_id: str,
        path: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.options.apply:
            result = self.ir.post(path, payload)
            if not isinstance(result, dict):
                result = {}
            self.reporter.add(
                "info",
                entity,
                "create",
                "created in IncidentRelay",
                source_id,
                incidentrelay_id=result.get("id"),
            )
            return result
        planned = {"id": self.planned_id()}
        self.reporter.add(
            "info",
            entity,
            "plan",
            "would create in IncidentRelay",
            source_id,
            endpoint=path,
            name=payload.get("name") or payload.get("username"),
        )
        return planned


# ----------------------------- conversion helpers -----------------------------


def rotation_fields(layer: Mapping[str, Any], timezone_name: str) -> dict[str, Any]:
    duration = int(layer.get("rotation_turn_length_seconds") or 86400)
    rotation_type, interval_value, interval_unit = choose_interval(duration)
    start_value = (
        layer.get("rotation_virtual_start")
        or layer.get("start")
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    source_start = parse_datetime_raw(start_value) or datetime.now(timezone.utc)
    start = source_start.astimezone(timezone.utc) if source_start.tzinfo else source_start.replace(tzinfo=timezone.utc)
    handoff_weekday = source_start.weekday() if rotation_type == "weekly" else None
    return {
        "start_at": iso_z(start),
        "rotation_type": rotation_type,
        "interval_value": interval_value,
        "interval_unit": interval_unit,
        "handoff_time": source_start.strftime("%H:%M"),
        "handoff_weekday": handoff_weekday,
        "timezone": timezone_name or "UTC",
        "duration_seconds": duration,
    }


def choose_interval(duration_seconds: int) -> tuple[str, int, str]:
    duration = max(int(duration_seconds or 0), 60)
    if duration == 86400:
        return "daily", 1, "days"
    if duration == 604800:
        return "weekly", 1, "weeks"
    for unit, seconds in (
        ("weeks", 604800),
        ("days", 86400),
        ("hours", 3600),
        ("minutes", 60),
    ):
        if duration % seconds == 0:
            value = duration // seconds
            if 1 <= value <= 365:
                return "custom", value, unit
    # IncidentRelay custom intervals are minute-granular. Round up rather than
    # shortening PagerDuty coverage.
    value = min(max((duration + 59) // 60, 1), 365)
    return "custom", value, "minutes"


def convert_restrictions(
    restrictions: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    converted: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in restrictions:
        kind = str(item.get("type") or "").lower()
        start_text = normalize_time(item.get("start_time_of_day") or "00:00:00")
        duration = int(item.get("duration_seconds") or 0)
        if duration <= 0:
            warnings.append("restriction with non-positive duration was skipped")
            continue
        if duration >= 86400:
            warnings.append("full-day restriction was omitted because the layer is already continuously active")
            continue
        end_text = add_seconds_to_time(start_text, duration)
        weekday: int | None = None
        if kind == "weekly_restriction":
            pd_day = int(item.get("start_day_of_week") or 1)
            weekday = max(0, min(6, pd_day - 1))
        elif kind not in {"daily_restriction", ""}:
            warnings.append(f"unsupported restriction type {kind!r} was skipped")
            continue
        converted.append(
            {"weekday": weekday, "start_time": start_text, "end_time": end_text}
        )
    return dedupe_dicts(converted), warnings


def normalize_time(value: Any) -> str:
    text = str(value or "00:00").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})", text)
    if not match:
        return "00:00"
    hour = max(0, min(23, int(match.group(1))))
    minute = max(0, min(59, int(match.group(2))))
    return f"{hour:02d}:{minute:02d}"


def add_seconds_to_time(start: str, seconds: int) -> str:
    hour, minute = [int(part) for part in start.split(":", 1)]
    total_minutes = (hour * 60 + minute + (seconds + 59) // 60) % (24 * 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def restriction_signatures(items: Sequence[Mapping[str, Any]]) -> set[tuple[Any, ...]]:
    return {
        (
            int_or_none(item.get("weekday")),
            normalize_time(item.get("start_time")),
            normalize_time(item.get("end_time")),
        )
        for item in items
    }



def parse_datetime_raw(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def normalize_iso(value: Any) -> str | None:
    parsed = parse_datetime(value)
    return iso_z(parsed) if parsed else None


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def prefixed_name(prefix: str, value: Any, limit: int) -> str:
    base = str(value or "").strip()
    prefix = str(prefix or "")
    result = str(truncate(f"{prefix}{base}", limit) or "")
    if limit >= 2 and len(result) < 2:
        result = str(truncate(f"{result} imported".strip(), limit) or "imported")
    return result


def truncate(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def slugify(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "imported"


def unique_slug(name: Any, used: set[str], *, suffix: str) -> str:
    base = slugify(name)[:48].strip("-") or "imported"
    candidate = base
    if candidate not in used:
        return candidate
    short = slugify(suffix)[-8:] or stable_hash(suffix)[:8]
    candidate = f"{base[: max(1, 63 - len(short) - 1)]}-{short}"
    counter = 2
    while candidate in used:
        tail = f"-{short}-{counter}"
        candidate = f"{base[: max(1, 64 - len(tail))]}{tail}"
        counter += 1
    return candidate


def unique_username(
    user: Mapping[str, Any],
    existing_by_username: Mapping[str, Any],
) -> str:
    email = normalize_email(user.get("email"))
    base = email.split("@", 1)[0] if email else str(user.get("name") or "pagerduty-user")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._") or "pagerduty-user"
    base = base[:32]
    candidate = base
    source_id = str(user.get("id") or "")
    if candidate.lower() not in existing_by_username:
        return candidate
    suffix = stable_hash(source_id or email or base)[:7]
    candidate = f"{base[:32]}-{suffix}"[:40]
    counter = 2
    while candidate.lower() in existing_by_username:
        tail = f"-{counter}"
        candidate = f"{base[:40-len(tail)]}{tail}"
        counter += 1
    return candidate


def object_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(value or "")


def nested_id(value: Any) -> int | None:
    return int_or_none(value.get("id")) if isinstance(value, dict) else int_or_none(value)


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def by_id(items: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): dict(item) for item in items if item.get("id")}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in as_list(value) if isinstance(item, dict)]


def unique_ints(values: Iterable[int]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def dedupe_dicts(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        item = dict(value)
        marker = json.dumps(item, sort_keys=True, default=str)
        if marker not in seen:
            result.append(item)
            seen.add(marker)
    return result


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_json_bytes(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"message": raw.decode("utf-8", errors="replace")[:1000]}


def api_message(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "errors"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return "; ".join(str(item) for item in value)
            if isinstance(value, dict):
                return json.dumps(value, ensure_ascii=False)
    return ""


def retry_delay(headers: Any, attempt: int) -> float:
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after:
        try:
            return min(max(float(retry_after), 0.5), 60.0)
        except ValueError:
            pass
    reset = headers.get("X-RateLimit-Reset") if headers else None
    if reset:
        try:
            return min(max(float(reset) - time.time(), 0.5), 60.0)
        except ValueError:
            pass
    return float(min(2**attempt, 20))


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="<redacted>" if parsed.query else "").geturl()


def json_scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write(path, text, mode=None)


def write_json_secure(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write(path, text, mode=0o600)


def atomic_write(path: Path, text: str, *, mode: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
        if mode is not None:
            os.chmod(path, mode)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def write_route_csv(secret_path: Path, csv_path: Path) -> None:
    if not secret_path.exists():
        return
    payload = json.loads(secret_path.read_text(encoding="utf-8"))
    rows = []
    for item in payload.get("routes", {}).values():
        rows.append(
            {
                "pagerduty_service_id": item.get("pagerduty_service_id"),
                "pagerduty_service_name": item.get("pagerduty_service_name"),
                "incidentrelay_route_id": item.get("incidentrelay_route_id"),
                "endpoint": item.get("endpoint"),
                "routing_key": item.get("routing_key"),
            }
        )
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.chmod(csv_path, 0o600)


def parse_stages(value: str) -> set[str]:
    stages = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = stages - set(MIGRATION_STAGES)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown stages: {', '.join(sorted(unknown))}; valid: {', '.join(MIGRATION_STAGES)}"
        )
    return stages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate PagerDuty configuration to IncidentRelay through HTTP APIs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pagerduty-token",
        default=os.getenv("PAGERDUTY_TOKEN"),
        help="PagerDuty REST API token; can also use PAGERDUTY_TOKEN",
    )
    parser.add_argument(
        "--pagerduty-url",
        default=os.getenv("PAGERDUTY_URL", DEFAULT_PD_URL),
        help="PagerDuty API base URL; use https://api.eu.pagerduty.com for EU accounts",
    )
    parser.add_argument(
        "--pagerduty-from",
        default=os.getenv("PAGERDUTY_FROM"),
        help="Optional PagerDuty From header email",
    )
    parser.add_argument(
        "--incidentrelay-url",
        default=os.getenv("INCIDENTRELAY_URL"),
        help="IncidentRelay base URL; can also use INCIDENTRELAY_URL",
    )
    parser.add_argument(
        "--incidentrelay-token",
        default=os.getenv("INCIDENTRELAY_TOKEN"),
        help="IncidentRelay admin API token; can also use INCIDENTRELAY_TOKEN",
    )
    parser.add_argument("--group-id", required=True, type=int, help="Target IncidentRelay group ID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform writes. Without this flag the command is a dry-run.",
    )
    parser.add_argument(
        "--only",
        type=parse_stages,
        default=set(MIGRATION_STAGES),
        help="Comma-separated stages: users,teams,schedules,policies,services,maintenance",
    )
    parser.add_argument(
        "--missing-users",
        choices=("skip", "create-active", "create-inactive"),
        default="create-active",
        help="How to handle PagerDuty users not matched by email",
    )
    parser.add_argument(
        "--group-role",
        choices=("viewer", "editor", "user_admin"),
        default="viewer",
        help="IncidentRelay group role for migrated users",
    )
    parser.add_argument(
        "--team-role",
        choices=("viewer", "responder", "manager"),
        default="responder",
        help="Default IncidentRelay team role",
    )
    parser.add_argument(
        "--name-prefix",
        default="PD — ",
        help="Prefix added to created team, rotation, policy, service and route names",
    )
    parser.add_argument(
        "--fallback-team-name",
        default="Imported",
        help="Fallback team for PagerDuty resources with no team",
    )
    parser.add_argument(
        "--overrides-until-days",
        type=int,
        default=365,
        help="How many future days of schedule overrides to import",
    )
    parser.add_argument(
        "--skip-routes",
        action="store_true",
        help="Do not create PagerDuty Events API v2-compatible Webhook routes for services",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("pagerduty-migration-output"),
        help="Snapshots, report, state and generated route secrets",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--insecure-pagerduty", action="store_true")
    parser.add_argument("--insecure-incidentrelay", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on the first conversion warning",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    missing = []
    if not args.pagerduty_token:
        missing.append("--pagerduty-token or PAGERDUTY_TOKEN")
    if not args.incidentrelay_url:
        missing.append("--incidentrelay-url or INCIDENTRELAY_URL")
    if not args.incidentrelay_token:
        missing.append("--incidentrelay-token or INCIDENTRELAY_TOKEN")
    if missing:
        raise MigrationError("missing required configuration: " + ", ".join(missing))
    if args.overrides_until_days < 0:
        raise MigrationError("--overrides-until-days must be zero or greater")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_args(args)
        output_dir: Path = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        reporter = Reporter(strict=args.strict)
        state = StateStore(output_dir / "state.json", persist=args.apply)
        secrets = SecretStore(output_dir / "route-secrets.json", persist=args.apply)
        pd = PagerDutyClient(
            args.pagerduty_url,
            args.pagerduty_token,
            from_email=args.pagerduty_from,
            verify_tls=not args.insecure_pagerduty,
            timeout=args.timeout,
            retries=args.retries,
        )
        ir = IncidentRelayClient(
            args.incidentrelay_url,
            args.incidentrelay_token,
            verify_tls=not args.insecure_incidentrelay,
            timeout=args.timeout,
            retries=args.retries,
        )
        options = MigrationOptions(
            apply=args.apply,
            group_id=args.group_id,
            selected_stages=set(args.only),
            missing_users=args.missing_users,
            group_role=args.group_role,
            team_role=args.team_role,
            name_prefix=args.name_prefix,
            fallback_team_name=args.fallback_team_name,
            overrides_until_days=args.overrides_until_days,
            create_routes=not args.skip_routes,
            strict=args.strict,
        )
        migrator = Migrator(pd, ir, state, secrets, reporter, options)
        migrator.run(output_dir)
        metadata = {
            "mode": "apply" if args.apply else "dry-run",
            "generated_at": iso_z(datetime.now(timezone.utc)),
            "pagerduty_url": args.pagerduty_url,
            "incidentrelay_url": args.incidentrelay_url,
            "group_id": args.group_id,
            "stages": sorted(args.only),
        }
        reporter.write(output_dir, metadata)
        if args.apply:
            state.save()
            write_route_csv(
                output_dir / "route-secrets.json",
                output_dir / "route-switch-map.csv",
            )
        summary = reporter.summary()["levels"]
        print("\nMigration completed.")
        print(f"Mode: {'apply' if args.apply else 'dry-run'}")
        print(f"Report: {output_dir / 'report.md'}")
        print(f"Warnings: {summary.get('warning', 0)}")
        if args.apply:
            print(f"State: {output_dir / 'state.json'}")
            if (output_dir / "route-secrets.json").exists():
                print(f"Route secrets: {output_dir / 'route-secrets.json'}")
        return 0
    except (MigrationError, ApiError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
