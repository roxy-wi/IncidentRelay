#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_REPO = "roxy-wi/IncidentRelay"
ARCH_EN = Path("docs/architecture/incident-management-v2.md")
ARCH_RU = Path("docs/ru/architecture/incident-management-v2.md")
ROADMAP_START = "<!-- incident-management-roadmap:start -->"
ROADMAP_END = "<!-- incident-management-roadmap:end -->"
ARCH_BOUNDARY_MARKER = "incidentrelay-v2-final-boundaries"
EPIC_CLEANUP_MARKER = "incidentrelay-v2-cleanup-gate"
COMMENT_83_MARKER = "<!-- incidentrelay-issue-83-maintainer-response:v1 -->"
COMMENT_84_MARKER = "<!-- incidentrelay-issue-84-roadmap-comment:v1 -->"
COMMENT_60_MARKER = "<!-- incidentrelay-issue-60-roadmap:v1 -->"
CLEANUP_TITLE = "Incident Management v2: final legacy cleanup and model convergence"


def cmd(*args: str, input_text: str | None = None, check: bool = True):
    return subprocess.run(
        list(args), input=input_text, text=True, capture_output=True, check=check
    )


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip() + "\n"


def ensure_environment() -> None:
    if not ARCH_EN.exists():
        raise SystemExit(
            f"{ARCH_EN} not found. Run this script from the IncidentRelay repo root."
        )
    try:
        cmd("gh", "--version")
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise SystemExit("GitHub CLI (`gh`) is required.")
    if cmd("gh", "auth", "status", check=False).returncode != 0:
        raise SystemExit("GitHub CLI is not authenticated. Run `gh auth login`.")


def managed_block(marker: str, content: str) -> str:
    return f"<!-- {marker}:start -->\n{content.strip()}\n<!-- {marker}:end -->"


def upsert_managed_block(text: str, marker: str, content: str, before_anchor: str) -> str:
    text = normalize(text)
    block = managed_block(marker, content)
    pattern = re.compile(
        re.escape(f"<!-- {marker}:start -->")
        + r".*?"
        + re.escape(f"<!-- {marker}:end -->"),
        re.S,
    )
    if pattern.search(text):
        return normalize(pattern.sub(block, text, count=1))
    if before_anchor not in text:
        raise RuntimeError(
            f"Cannot insert {marker}: anchor {before_anchor!r} was not found"
        )
    before, after = text.split(before_anchor, 1)
    return normalize(
        before.rstrip() + "\n\n" + block + "\n\n" + before_anchor + after
    )


def replace_heading_range(text: str, start_pattern: str, end_pattern: str, replacement: str) -> str:
    text = normalize(text)
    start = re.search(start_pattern, text, re.M)
    if not start:
        raise RuntimeError(f"Start heading not found: {start_pattern}")
    end = re.search(end_pattern, text[start.end():], re.M)
    if not end:
        raise RuntimeError(f"End heading not found: {end_pattern}")
    end_pos = start.end() + end.start()
    return normalize(
        text[:start.start()].rstrip()
        + "\n\n"
        + replacement.strip()
        + "\n\n"
        + text[end_pos:].lstrip()
    )


def remove_managed_block(text: str, marker: str) -> str:
    text = normalize(text)
    pattern = re.compile(
        r"\n*" + re.escape(f"<!-- {marker}:start -->")
        + r".*?"
        + re.escape(f"<!-- {marker}:end -->") + r"\n*",
        re.S,
    )
    return normalize(pattern.sub("\n\n", text))


def show_diff(label: str, old: str, new: str) -> None:
    old, new = normalize(old), normalize(new)
    if old == new:
        print(f"{label}: no change")
        return
    print(f"\n===== {label} =====")
    print("\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{label}:before", tofile=f"{label}:after", lineterm=""
    )))


ARCH_BOUNDARIES_EN = r'''
### AlertGroup and Incident responsibility boundary

The target model intentionally keeps both objects useful:

```text
Alert -> AlertGroup        technical signal episode
             -> Incident   optional operational investigation
```

`AlertGroup` remains responsible for technical signal processing:

- child Alert occurrences, grouping and deduplication;
- technical lifecycle and source state;
- routing, notification and escalation;
- technical assignee and manual AlertGroup reassignment;
- technical priority/context, Silence, maintenance and shelving;
- impact, correlation and source context;
- technical timeline;
- **technical comments**.

`Incident` owns operational response:

- independent operational workflow;
- operational assignee and manual Incident reassignment;
- Incident Commander and responders;
- stakeholders;
- affected-service context;
- **operational comments**;
- root cause and resolution summary;
- external ITSM references;
- postmortem and corrective actions.

Assignment rules:

```text
AlertGroup.assignee = current technical responsibility / paging target
Incident.assignee   = owner of the operational investigation
```

Both assignments may be changed manually, but they are independent. Changing
one must not silently mutate the other. AlertGroup reassignment does not imply
ACK and does not reset escalation policy, escalation level, rotation or the
next scheduled escalation.

Proposal #83 is interpreted primarily as manual reassignment of the current
AlertGroup assignee because the current product exposes AlertGroups as
"incidents". First-class Incident reassignment remains a separate required
Incident Core capability.

Comment rules:

- AlertGroup comments remain supported as technical investigation notes;
- Incident comments are operational collaboration;
- a combined Incident activity view may surface comments from linked
  AlertGroups, but must identify the original target/source;
- comments are not automatically copied between AlertGroup and Incident;
- original author, timestamp and target remain canonical.

Responder/stakeholder rules:

- responders and stakeholders become canonical Incident collaboration data;
- service default stakeholders are copied as Incident snapshots;
- legacy AlertGroup responder/stakeholder records are preserved during staged
  migration;
- final removal of legacy operational AlertGroup storage belongs to 2.9;
- AlertGroup technical comments are explicitly not removed by that cleanup.
'''

ARCH_BOUNDARIES_RU = r'''
### Граница ответственности AlertGroup и Incident

Целевая модель сохраняет обе сущности полноценными:

```text
Alert -> AlertGroup        технический эпизод сигнала
             -> Incident   необязательное операционное расследование
```

`AlertGroup` продолжает отвечать за:

- child Alert occurrence, grouping и deduplication;
- technical lifecycle и source state;
- routing, notification и escalation;
- technical assignee и ручное переназначение AlertGroup;
- technical priority/context, Silence, maintenance и shelving;
- impact, correlation и source context;
- technical timeline;
- **технические комментарии**.

`Incident` отвечает за:

- независимый operational workflow;
- operational assignee и ручное переназначение Incident;
- Incident Commander и responders;
- stakeholders;
- affected-service context;
- **операционные комментарии**;
- root cause и resolution summary;
- external ITSM references;
- postmortem и corrective actions.

```text
AlertGroup.assignee = текущая техническая ответственность / paging target
Incident.assignee   = владелец операционного расследования
```

Оба назначения можно менять вручную, но они независимы. AlertGroup reassignment
не означает ACK и не сбрасывает escalation policy, escalation level, rotation
или next scheduled escalation.

#83 трактуется прежде всего как ручное переназначение текущего
`AlertGroup.assignee`, потому что текущий UI называет AlertGroup инцидентом.
Ручное переназначение first-class Incident остаётся отдельной capability 2.3.

Комментарии:

- AlertGroup comments остаются техническими заметками;
- Incident comments используются для operational collaboration;
- combined Incident activity может показывать комментарии linked AlertGroup с
  явным source/target;
- комментарии не копируются автоматически между объектами.

Responders/stakeholders:

- canonical ownership переходит в Incident;
- legacy AlertGroup records сохраняются во время staged migration;
- окончательное удаление legacy operational storage относится к 2.9;
- technical comments AlertGroup cleanup не удаляет.
'''

ARCH_ROADMAP_EN = r'''
## 18. Versioned delivery roadmap

### IncidentRelay 2.3: Incident Core and ownership

- first-class `Incident` and `IncidentAlertGroupLink`;
- manual Incident creation, Create Incident from AlertGroup, basic link/unlink;
- independent Incident lifecycle, team/service/priority;
- manual Incident assign/reassign/unassign and **Assign to me**;
- manual AlertGroup assign/reassign and **Assign to me** for #83;
- AlertGroup reassignment does not ACK or reset escalation state;
- breaking `/api/alert-groups` vs `/api/incidents` split;
- separate Alerts/Incidents navigation and minimal Incident workspace;
- preserve AlertGroup technical comments;
- RBAC, audit, timeline, migrations, concurrency, OpenAPI and docs.

### IncidentRelay 2.4: Lifecycle resilience and flapping

- #84/#85 `set_grouping.reopen_window_seconds` controlled by Event Orchestration;
- disabled by default;
- reopen creates a new child Alert; older resolved child Alerts remain terminal;
- resolve/reopen and duplicate-delivery concurrency protection;
- linked resolved/monitoring Incident may return to `investigating`;
- recovery notification hysteresis / delayed resolved notification;
- cancel pending recovery notification on quick reopen;
- Explain, audit, timeline and UI context.

### IncidentRelay 2.5: Incident collaboration

- Incident Commander and responders;
- Incident stakeholders and service-default stakeholder snapshots;
- Incident operational comments and richer activity;
- root cause and resolution summary;
- affected services and runbook/dashboard/dependency/impact context;
- preserve AlertGroup technical comments as a separate target;
- combined Incident activity may show linked AlertGroup comments with explicit
  source attribution;
- staged migration of legacy AlertGroup responder/stakeholder data when an
  unambiguous Incident mapping exists;
- never backfill an Incident solely to move legacy collaboration data.

### IncidentRelay 2.6: Classification, relations and merge/split

- AlertGroup classification and review policy;
- review-required queue;
- duplicate canonical AlertGroup/Incident targets;
- `primary`, `related`, `symptom`, `duplicate` relations;
- Incident merge and split;
- technical AlertGroup merge/link reconciliation;
- RBAC, audit, history and concurrency coverage.

### IncidentRelay 2.7: On-call Roles and Incident automation

- #59 On-call Roles and concurrent role-aware coverage;
- role-aware Incident assignee/commander/responder suggestions;
- persist concrete users rather than live schedule ownership links;
- #51 Event Orchestration Incident declaration/linking/assignment actions;
- draft-and-confirm, similar-open-Incident checks and idempotency;
- asynchronous duration/escalation hooks;
- optional stale-signal policy, disabled by default;
- inactivity alone never means technical recovery.

### IncidentRelay 2.8: ITSM and Jira

- #52 `IncidentExternalReference` and provider-neutral ITSM framework;
- manual external references, protected connector configuration;
- outbox, retries, idempotency and dead-letter visibility;
- #53 Jira/Jira Service Management create/update;
- authenticated inbound events, source-of-truth/conflict handling;
- sync-loop prevention, secret redaction and SSRF/private-network controls.

### IncidentRelay 2.9: Analytics, Postmortems and final cleanup

- #54 Incident and AlertGroup analytics with exact lifecycle definitions;
- separate Incident reopen and AlertGroup reopen/flapping metrics;
- classification, alert-quality and external-ticket metrics;
- #60 configurable Postmortems / Incident Reviews;
- corrective actions with owner/due date and export/reporting;
- final Incident v2 cleanup;
- remove deprecated AlertGroup responder/stakeholder write flows only after
  reconciliation;
- preserve AlertGroup technical comments and Incident operational comments;
- remove legacy Incident-as-AlertGroup terminology/helpers/adapters;
- remove obsolete compatibility DB structures only through explicit,
  idempotent migrations with reconciliation and documented rollback boundary;
- never create historical Incidents solely to simplify cleanup.

### Cross-release hardening rule

Every release includes the RBAC, audit, timeline, migrations, concurrency,
OpenAPI, localization, tests and documentation required by its own scope.
'''

ARCH_ROADMAP_RU = r'''
## 18. Версионированный план поставки

### IncidentRelay 2.3: Incident Core и ownership

- first-class `Incident` и `IncidentAlertGroupLink`;
- manual Incident, Create Incident from AlertGroup, basic link/unlink;
- independent Incident lifecycle, team/service/priority;
- manual Incident assign/reassign/unassign и **Assign to me**;
- manual AlertGroup assign/reassign и **Assign to me** для #83;
- AlertGroup reassignment не делает ACK и не сбрасывает escalation state;
- breaking `/api/alert-groups` vs `/api/incidents` split;
- отдельные Alerts/Incidents UI и минимальный Incident workspace;
- technical comments AlertGroup сохраняются;
- RBAC, audit, timeline, migrations, concurrency, OpenAPI и docs.

### IncidentRelay 2.4: Lifecycle resilience и flapping

- #84/#85 Event Orchestration `set_grouping.reopen_window_seconds`;
- disabled by default;
- reopen создаёт новый child Alert, старые resolved child Alert остаются terminal;
- concurrency для resolve/reopen и duplicate delivery;
- linked resolved/monitoring Incident может вернуться в `investigating`;
- recovery notification hysteresis / delayed resolved notification;
- отмена pending recovery notification при быстром reopen;
- Explain, audit, timeline и UI context.

### IncidentRelay 2.5: Incident collaboration

- Incident Commander и responders;
- Incident stakeholders и snapshot service-default stakeholders;
- operational comments Incident и richer activity;
- root cause и resolution summary;
- affected services и runbook/dashboard/dependency/impact context;
- technical comments AlertGroup остаются отдельным target;
- combined Incident activity может показывать comments linked AlertGroup с
  явным source attribution;
- staged migration legacy AlertGroup responder/stakeholder data при наличии
  однозначного Incident mapping;
- Incident не создаётся задним числом только ради migration collaboration data.

### IncidentRelay 2.6: Classification, relations и merge/split

- AlertGroup classification и review policy;
- review-required queue;
- duplicate canonical AlertGroup/Incident targets;
- relation types `primary`, `related`, `symptom`, `duplicate`;
- Incident merge/split;
- technical AlertGroup merge/link reconciliation;
- RBAC, audit, history и concurrency.

### IncidentRelay 2.7: On-call Roles и Incident automation

- #59 On-call Roles и concurrent role-aware coverage;
- role-aware suggestions assignee/commander/responders;
- concrete users вместо live schedule ownership links;
- #51 Event Orchestration Incident actions;
- draft-and-confirm, similar-open-Incident checks, idempotency;
- async duration/escalation hooks;
- optional stale-signal policy, disabled by default;
- inactivity сама по себе не означает recovery.

### IncidentRelay 2.8: ITSM и Jira

- #52 `IncidentExternalReference` и provider-neutral ITSM;
- manual external references, protected connector config;
- outbox, retries, idempotency, dead-letter;
- #53 Jira/JSM create/update;
- authenticated inbound events, source-of-truth/conflict handling;
- sync-loop prevention, secret redaction, SSRF/private-network controls.

### IncidentRelay 2.9: Analytics, Postmortems и final cleanup

- #54 analytics Incident/AlertGroup с точными lifecycle definitions;
- отдельные Incident reopen и AlertGroup reopen/flapping metrics;
- classification, alert-quality и external-ticket metrics;
- #60 configurable Postmortems / Incident Reviews;
- corrective actions с owner/due date и export/reporting;
- final Incident v2 cleanup;
- deprecated AlertGroup responder/stakeholder write flows удаляются только после
  reconciliation;
- technical comments AlertGroup и operational comments Incident сохраняются;
- удаляются legacy Incident-as-AlertGroup terminology/helpers/adapters;
- obsolete compatibility DB structures удаляются только explicit idempotent
  migrations с reconciliation и rollback boundary;
- historical Incident не создаются только ради cleanup.

### Cross-release hardening rule

Каждый релиз включает RBAC, audit, timeline, migrations, concurrency, OpenAPI,
localization, tests и docs для собственного scope.
'''

ARCH_GATE_EN = r'''
## 19. IncidentRelay 2.3 release gate

Incident Core is ready to ship in 2.3 when:

- Alert, AlertGroup and Incident boundaries are explicit and tested;
- AlertGroup remains a first-class technical signal episode;
- `/api/alert-groups` exposes AlertGroups and `/api/incidents` exposes only
  first-class Incidents;
- manual AlertGroup creation creates one group and one child Alert atomically;
- manual Incident creation creates only an Incident;
- Incidents can exist with zero or multiple linked AlertGroups;
- linked AlertGroups retain their technical lifecycle;
- authorized operators can manually reassign AlertGroup assignee;
- AlertGroup reassignment does not ACK or reset escalation policy/state;
- authorized operators can assign/reassign/unassign Incident ownership;
- AlertGroup and Incident assignments are independent;
- AlertGroup technical comments remain supported;
- minimal Incident UI, RBAC, audit, migration, concurrency and OpenAPI are
  production-ready;
- 2.4 flapping/reopen behavior is not required to ship 2.3.

Later collaboration, classification, role-aware scheduling, automation, ITSM,
analytics, postmortems and cleanup are not blockers for 2.3.
'''

ARCH_GATE_RU = r'''
## 19. Release gate IncidentRelay 2.3

Incident Core готов к 2.3, когда:

- границы Alert, AlertGroup и Incident явны и протестированы;
- AlertGroup остаётся полноценным technical signal episode;
- `/api/alert-groups` представляет AlertGroup, `/api/incidents` — только
  first-class Incident;
- manual AlertGroup атомарно создаёт group и один child Alert;
- manual Incident создаёт только Incident;
- Incident может иметь ноль или несколько linked AlertGroup;
- linked AlertGroup сохраняют собственный technical lifecycle;
- authorized operator может вручную reassign AlertGroup assignee;
- AlertGroup reassignment не делает ACK и не сбрасывает escalation state;
- authorized operator может assign/reassign/unassign Incident ownership;
- AlertGroup и Incident assignments независимы;
- technical comments AlertGroup остаются поддерживаемыми;
- минимальный Incident UI, RBAC, audit, migration, concurrency и OpenAPI
  production-ready;
- flapping/reopen behavior 2.4 не блокирует 2.3.

Collaboration, classification, role-aware scheduling, automation, ITSM,
analytics, postmortems и cleanup более поздних релизов не блокируют 2.3.
'''

EPIC_RELEASES = r'''
# IncidentRelay 2.3 — Incident Core and ownership

## Scope
- [ ] First-class `Incident` and `IncidentAlertGroupLink`.
- [ ] Manual Incident creation, Create Incident from AlertGroup, basic link/unlink.
- [ ] Independent Incident workflow and explicit close/reopen.
- [ ] Incident team/service/priority/operational assignee.
- [ ] Manual Incident assign/reassign/unassign and **Assign to me**.
- [ ] Manual AlertGroup assign/reassign and **Assign to me** for #83.
- [ ] AlertGroup reassignment does not ACK or reset escalation state.
- [ ] Breaking `/api/alert-groups` vs `/api/incidents` split.
- [ ] Minimal separate Alerts/Incidents UI.
- [ ] Preserve AlertGroup technical comments.
- [ ] RBAC, audit, timeline, migration, concurrency, OpenAPI and docs.

## 2.3 workstreams
- #47 — Incident domain model and migration
- #48 — AlertGroup/Incident API split
- #49 — minimal separate Alerts/Incidents UI
- #55 — release hardening
- #83 — AlertGroup reassignment proposal

---

# IncidentRelay 2.4 — Lifecycle resilience and flapping

## Scope
- [ ] #84/#85 Event Orchestration controlled `reopen_window_seconds`.
- [ ] Disabled by default; new child Alert on reopen.
- [ ] Resolve/reopen concurrency safety.
- [ ] Linked Incident reopen synchronization.
- [ ] Recovery notification hysteresis / delayed resolved notifications.
- [ ] Reopen/flapping Explain, audit, timeline and UI context.

## 2.4 workstreams
- #85 — flapping-safe AlertGroup reopen lifecycle
- #49 — reopen UI integration
- #55 — hardening

---

# IncidentRelay 2.5 — Incident Collaboration

## Scope
- [ ] Commander/responders.
- [ ] Incident stakeholders and service-default snapshots.
- [ ] Incident operational comments and richer activity.
- [ ] Root cause / resolution summary.
- [ ] Affected services and runbook/dashboard/dependency/impact context.
- [ ] Preserve AlertGroup technical comments as separate target.
- [ ] Staged migration of legacy AlertGroup responder/stakeholder data.

## 2.5 workstreams
- #47 — collaboration-domain migration subset
- #49 — collaboration workspace
- #55 — hardening

---

# IncidentRelay 2.6 — Classification, relations and merge/split

## Scope
- [ ] AlertGroup classification/review policy.
- [ ] Duplicate canonical targets and relation types.
- [ ] Incident merge/split.
- [ ] AlertGroup merge/link reconciliation.

## 2.6 workstreams
- #46 — classification/review
- #50 — relations, merge/split, duplicate handling
- #49 — UI
- #55 — hardening

---

# IncidentRelay 2.7 — On-call Roles and Incident Automation

## Scope
- [ ] #59 On-call Roles and role-aware assignment/participants.
- [ ] #51 Event Orchestration Incident actions.
- [ ] Automatic declaration/linking/explicit assignment.
- [ ] Idempotency and async duration/escalation hooks.
- [ ] Optional stale-signal policy; inactivity is not recovery by default.

## 2.7 workstreams
- #51 — automation/orchestration
- #59 — On-call Roles
- #55 — hardening

---

# IncidentRelay 2.8 — ITSM and Jira

## Scope
- [ ] #52 generic external-reference/ITSM framework.
- [ ] Outbox/retries/dead-letter/inbound/conflict handling.
- [ ] #53 Jira/JSM connector.
- [ ] Security, secret redaction and SSRF controls.

## 2.8 workstreams
- #52 — generic ITSM framework
- #53 — Jira/JSM
- #55 — hardening

---

# IncidentRelay 2.9 — Analytics, Postmortems and final cleanup

## Scope
- [ ] #54 Incident and alert-quality analytics.
- [ ] Exact lifecycle/reopen/flapping/external-ticket metrics.
- [ ] #60 Postmortems / Incident Reviews and corrective actions.
- [ ] Final Incident v2 cleanup.
- [ ] Remove deprecated AlertGroup responder/stakeholder writes after reconciliation.
- [ ] Preserve AlertGroup technical comments and Incident operational comments.
- [ ] Remove legacy Incident-as-AlertGroup terminology/helpers/adapters.
- [ ] Remove obsolete DB compatibility structures only through explicit,
      idempotent migrations with reconciliation and rollback boundary.
- [ ] Never create historical Incidents solely for cleanup.

## 2.9 workstreams
- #54 — analytics
- #60 — Postmortems / Incident Reviews
- {cleanup_ref} — final legacy cleanup and model convergence
- #55 — final hardening
'''

ISSUE_ALLOCATIONS = {
46: '''## Release allocation\n\n**Target release:** IncidentRelay 2.6 — Classification, relations and merge/split\n\nClassification/review is intentionally deferred until Incident Core, lifecycle resilience and collaboration are stable. Classification remains independent from both AlertGroup technical status and Incident workflow status.''',
47: '''## Release allocation\n\n**Target releases:** 2.3 core, 2.5 collaboration migration, 2.9 cleanup\n\n### 2.3\n- first-class Incident and links;\n- independent lifecycle/team/service/priority/operational assignee;\n- manual Incident reassignment;\n- preserve AlertGroup technical assignee/comments and all existing technical history.\n\n### 2.5\n- canonical Incident responders/stakeholders/operational comments;\n- staged migration of legacy AlertGroup responder/stakeholder data when mapping is unambiguous;\n- AlertGroup technical comments stay on AlertGroup and are not copied.\n\n### 2.9\n- remove deprecated AlertGroup responder/stakeholder writes after reconciliation;\n- preserve required historical/audit data;\n- never create Incidents solely to simplify cleanup.''',
48: '''## Release allocation\n\n**Target release:** IncidentRelay 2.3 — Incident Core and ownership\n\nThe breaking API split ships atomically in 2.3. AlertGroup API keeps technical lifecycle, technical comments and manual technical-assignee reassignment. Incident API owns independent operational lifecycle and operational-assignee reassignment.''',
49: '''## Release allocation\n\n**Target releases:** 2.3 minimal UI, 2.4 lifecycle UX, 2.5 collaboration, 2.6 relations/classification, 2.7 role-aware assignment.\n\n- 2.3: separate Alerts/Incidents UI plus AlertGroup and Incident reassignment.\n- 2.4: reopen/flapping visibility.\n- 2.5: responders, stakeholders, Incident comments and combined activity with explicit AlertGroup comment source.\n- 2.6: classification/relations/merge-split UX.\n- 2.7: On-call Role based suggestions/resolution.''',
50: '''## Release allocation\n\n**Target release:** IncidentRelay 2.6 — Classification, relations and merge/split\n\n2.3 keeps basic non-destructive Incident↔AlertGroup linking only. Advanced relations, duplicate canonical handling and Incident merge/split wait until collaboration is stable.''',
51: '''## Release allocation\n\n**Target release:** IncidentRelay 2.7 — On-call Roles and Incident Automation\n\nAutomation follows 2.3 Incident Core, 2.4 lifecycle resilience, 2.5 collaboration and 2.6 classification/relations. Event Orchestration remains deterministic/simulation-safe; mutating async work uses idempotent queues. 2.7 also owns the optional stale-signal policy from #84/#85; inactivity never means recovery by default.''',
52: '''## Release allocation\n\n**Target release:** IncidentRelay 2.8 — ITSM and Jira\n\nThe provider-neutral ITSM foundation is separated from 2.7 Incident automation. `IncidentExternalReference`, connector configuration, outbox/retries, inbound processing and conflict/source-of-truth behavior ship as a dedicated integration release.''',
53: '''## Release allocation\n\n**Target release:** IncidentRelay 2.8 — ITSM and Jira\n\nJira/JSM is the first active provider on #52 and must reuse shared Jira connection/client infrastructure rather than introducing an Incident-only Jira stack.''',
54: '''## Release allocation\n\n**Target release:** IncidentRelay 2.9 — Analytics, Postmortems and final cleanup\n\nAnalytics follows the stable 2.3-2.8 domain/lifecycle work. Reports distinguish AlertGroup technical metrics from Incident operational metrics, including #84/#85 reopen/flapping/stale-signal metrics.''',
55: '''## Release allocation\n\n**Target releases:** IncidentRelay 2.3-2.9, incremental hardening\n\n- 2.3: API/core migration, assignment RBAC/audit/concurrency, OpenAPI/UI upgrade docs.\n- 2.4: reopen/flapping concurrency, notification-hysteresis races, orchestration parity.\n- 2.5: collaboration migration/RBAC/history; preserve AlertGroup technical comments.\n- 2.6: classification/relation/merge-split concurrency/reconciliation.\n- 2.7: role-aware scheduling and automation idempotency/async safety.\n- 2.8: ITSM retries, inbound auth, redaction, SSRF and sync-loop protection.\n- 2.9: analytics/postmortem hardening and final cleanup reconciliation/migrations.\n\nEach release blocks only on its own epic #45 gate.''',
59: '''## Release allocation\n\n**Target release:** IncidentRelay 2.7 — On-call Roles and Incident Automation\n\nManual assignment exists earlier: 2.3 supports AlertGroup reassignment (#83) and independent Incident reassignment. 2.7 adds role-aware resolution; concrete users are persisted and later schedule rotation never silently replaces Incident assignments.''',
85: '''## Release allocation\n\n### IncidentRelay 2.4 — lifecycle resilience\n- Event Orchestration `set_grouping.reopen_window_seconds`; missing/zero = disabled;\n- new child Alert on reopen; resolved child Alerts remain terminal;\n- one eligible resolved AlertGroup reused inside the window; new group outside it;\n- route/team/service/grouping boundaries and resolve/reopen concurrency;\n- linked Incident reopen;\n- recovery notification hysteresis and cancellation on quick reopen;\n- Explain/timeline/audit/UI coverage.\n\n### IncidentRelay 2.7 — stale-signal follow-up\n- optional stale-signal policy, disabled by default;\n- async scheduler/worker evaluation; inactivity alone is not recovery.\n\n### IncidentRelay 2.9 — analytics\n- reopen/flapping/stale-signal metrics in #54.\n\nThis workstream is no longer a 2.3 release blocker.'''
}

EXTRA_BLOCKS = {
47: '''## Final responsibility boundary\n\n- AlertGroup keeps technical assignee, technical lifecycle and technical comments.\n- Incident keeps operational assignee, responders, stakeholders and operational comments.\n- Assignments never silently mutate each other.\n- Comments are not copied; combined activity preserves target/source.\n- Responders/stakeholders become canonical Incident records after collaboration cutover.''',
48: '''## Assignment API boundary\n\n2.3 must expose independent assignment mutation for both resources. AlertGroup reassignment changes only technical responsibility and does not ACK or reset escalation state. Incident reassignment changes only operational ownership. Neither API silently mutates the other object.''',
49: '''## Assignment and comment UI boundary\n\nAlerts UI exposes technical AlertGroup assignee/reassignment and technical comments. Incident UI exposes independent operational assignee/reassignment and operational comments. Combined Incident activity may render linked AlertGroup comments only with explicit source/target attribution.''',
55: '''## Final cleanup invariants\n\nKeep on AlertGroup: technical assignee/reassignment, technical comments, child Alerts/timeline, notification/escalation, Silence/maintenance/shelving, impact/correlation.\n\nCanonical on Incident: operational assignee, commander/responders, stakeholders, operational comments, root cause/resolution, postmortem/corrective actions.\n\nRemove legacy AlertGroup responder/stakeholder writes only after migration/reconciliation; never remove AlertGroup technical comments as part of cleanup.''',
59: '''## Relationship to proposal #83\n\n#83 is primarily manual reassignment of the current AlertGroup assignee. That 2.3 capability remains valid after first-class Incidents exist.\n\n2.7 On-call Roles extend but do not replace either manual AlertGroup reassignment or manual Incident reassignment; role resolution supplies concrete users and schedule rotation alone does not rewrite an Incident assignment.'''
}

CLEANUP_BODY = r'''Parent epic: #45

<!-- incident-management-roadmap:start -->
## Release allocation

**Target release:** IncidentRelay 2.9 — Analytics, Postmortems and final cleanup

This is the final convergence step after replacement Incident workflows have
shipped and been production-proven in 2.3-2.8.
<!-- incident-management-roadmap:end -->

## Goal

Remove the legacy mixed AlertGroup/Incident operational model without deleting
useful technical AlertGroup capabilities or losing historical data.

## Target responsibility boundary

Keep on AlertGroup:
- child Alerts, grouping/dedup and technical status;
- technical assignee and manual reassignment;
- routing, notifications and escalation;
- Silence, maintenance, shelving, impact and correlation;
- technical timeline;
- technical comments.

Canonical on Incident:
- operational assignee;
- Incident Commander/responders;
- stakeholders;
- operational comments;
- root cause/resolution;
- ITSM references;
- postmortem/corrective actions.

## Scope

- Remove deprecated AlertGroup responder/stakeholder write paths.
- Preserve AlertGroup technical comments permanently.
- Preserve Incident operational comments separately.
- Ensure combined Incident activity retains original comment target/source.
- Remove legacy Incident-as-AlertGroup terminology from backend/UI/OpenAPI/docs/tests/i18n.
- Remove temporary compatibility adapters/helpers.
- Remove obsolete operational AlertGroup fields/tables only via explicit migrations.
- Reconcile responder/stakeholder migration before destructive cleanup.
- Preserve historical/audit data required by supported retention policy.
- Do not create first-class Incidents solely to simplify cleanup.
- Verify notification/escalation no longer depends on operational stakeholder/responder storage.
- Document rollback boundary before destructive cleanup migrations.

## Acceptance criteria

- [ ] New AlertGroup responder/stakeholder records are no longer written.
- [ ] AlertGroup technical comments remain supported.
- [ ] Incident operational comments remain independent.
- [ ] Linking an AlertGroup never duplicates its comments into Incident.
- [ ] Historical responder/stakeholder data is migrated or explicitly retained with reconciliation counts.
- [ ] No supported historical data is silently dropped.
- [ ] No production API/UI treats AlertGroup as first-class Incident.
- [ ] Notification/escalation regression tests remain green after cleanup.
- [ ] Upgrade/reconciliation/rollback-boundary tests cover supported databases.

## Dependencies
- #47
- #49
- #54
- #55
- #60
'''

COMMENT_83 = f'''{COMMENT_83_MARKER}\nThanks for the proposal. We clarified the scope against the current data model.\n\nBecause IncidentRelay currently exposes `AlertGroup` as the day-to-day "incident", #83 is interpreted primarily as **manual reassignment of `AlertGroup.assignee`**.\n\n- **2.3:** AlertGroup **Assign to me** and manual Assign/Reassign.\n- Reassignment changes the technical assignee only.\n- It does **not** imply ACK and does not reset escalation policy, escalation level, rotation or next scheduled escalation.\n- Audit/timeline and concurrency protection are required.\n- First-class `Incident` also gets independent assign/reassign/unassign in 2.3.\n- `AlertGroup.assignee` and `Incident.assignee` remain separate.\n- **2.7 / #59:** On-call Roles add role-aware suggestions/resolution without removing either manual reassignment flow.\n\nTracking epic: #45\n'''

COMMENT_84 = f'''{COMMENT_84_MARKER}\nRoadmap update: #84 remains accepted, but lifecycle changes move out of the breaking 2.3 Incident Core release.\n\n- **2.4 / #85:** Event Orchestration controlled `set_grouping.reopen_window_seconds`, disabled by default; new child Alert on reopen; resolve/reopen concurrency; linked Incident reopen; recovery notification hysteresis.\n- **2.7:** optional stale-signal policy and asynchronous duration evaluation; inactivity alone is never recovery by default.\n- **2.9 / #54:** reopen/flapping/stale-signal analytics.\n\n`closed` remains an Incident workflow state, not an AlertGroup state. Resolved child Alerts remain terminal.\n\nTracking epic: #45\nImplementation workstream: #85\n'''

COMMENT_60 = f'''{COMMENT_60_MARKER}\nRoadmap update: configurable Postmortems / Incident Reviews are allocated to **IncidentRelay 2.9 — Analytics, Postmortems and final cleanup**.\n\nThe direction remains: separate Postmortem entity linked to Incident, Draft → Final lifecycle, configurable predefined sections, snapshot/auto-population from Incident/linked AlertGroups/services/dependencies/responders/activity, corrective actions with owner/due date, and portable export.\n\nTracking epic: #45\n'''


def format_roadmap(content: str) -> str:
    return f"{ROADMAP_START}\n{content.strip()}\n{ROADMAP_END}"


def replace_issue_roadmap(body: str, content: str) -> str:
    body = normalize(body)
    pattern = re.compile(re.escape(ROADMAP_START) + r".*?" + re.escape(ROADMAP_END), re.S)
    if not pattern.search(body):
        raise RuntimeError("Managed roadmap block not found in issue")
    return normalize(pattern.sub(format_roadmap(content), body, count=1))


def issue_json(repo: str, number: int) -> dict:
    return json.loads(cmd(
        "gh", "issue", "view", str(number), "--repo", repo,
        "--json", "number,title,body,state,url"
    ).stdout)


def edit_issue(repo: str, number: int, body: str, title: str | None = None) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(body)
        name = f.name
    try:
        args = ["gh", "issue", "edit", str(number), "--repo", repo, "--body-file", name]
        if title:
            args += ["--title", title]
        cmd(*args)
    finally:
        Path(name).unlink(missing_ok=True)


def find_exact_issue(repo: str, title: str):
    items = json.loads(cmd(
        "gh", "issue", "list", "--repo", repo, "--state", "all",
        "--search", f'"{title}" in:title', "--limit", "100",
        "--json", "number,title,state,url"
    ).stdout)
    return next((x for x in items if x.get("title") == title), None)


def create_cleanup_issue(repo: str):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(CLEANUP_BODY)
        name = f.name
    try:
        out = cmd(
            "gh", "issue", "create", "--repo", repo,
            "--title", CLEANUP_TITLE, "--body-file", name,
            "--label", "incident-management-v2"
        ).stdout.strip()
    finally:
        Path(name).unlink(missing_ok=True)
    return {"number": int(out.rstrip("/").split("/")[-1]), "url": out, "title": CLEANUP_TITLE}


def comments(repo: str, issue_number: int):
    return json.loads(cmd("gh", "api", f"repos/{repo}/issues/{issue_number}/comments?per_page=100").stdout)


def upsert_comment(repo: str, issue_number: int, marker: str, body: str, apply: bool) -> None:
    existing = next((x for x in comments(repo, issue_number) if marker in (x.get("body") or "")), None)
    if existing:
        old, new = normalize(existing.get("body") or ""), normalize(body)
        show_diff(f"issue #{issue_number} comment", old, new)
        if apply and old != new:
            cmd(
                "gh", "api", "--method", "PATCH",
                f"repos/{repo}/issues/comments/{existing['id']}", "--input", "-",
                input_text=json.dumps({"body": new})
            )
    else:
        print(f"\n===== issue #{issue_number} new comment =====\n{body.rstrip()}")
        if apply:
            cmd(
                "gh", "api", "--method", "POST",
                f"repos/{repo}/issues/{issue_number}/comments", "--input", "-",
                input_text=json.dumps({"body": normalize(body)})
            )


def revise_arch_en(text: str) -> str:
    text = normalize(text)
    text = text.replace(
        "- existing responders, stakeholders, comments and timeline.",
        "- technical comments and technical timeline;\n- legacy responder/stakeholder data only during staged migration.",
        1,
    )
    text = text.replace(
        "Responders, stakeholders, comments and operational timeline belong to the Incident. Notification and escalation state remain on `AlertGroup`.",
        "Responders, stakeholders and operational timeline belong to the Incident. Incident comments are operational collaboration; AlertGroup technical comments remain on AlertGroup. Notification and escalation state remain on `AlertGroup`.",
        1,
    )
    text = upsert_managed_block(text, ARCH_BOUNDARY_MARKER, ARCH_BOUNDARIES_EN, "## 4. Terminology")
    text = replace_heading_range(text, r"^## 18\..*$", r"^## 19\..*$", ARCH_ROADMAP_EN)
    text = replace_heading_range(text, r"^## 19\..*$", r"^## 20\..*$", ARCH_GATE_EN)
    return normalize(text.replace("2.3–2.6", "2.3–2.9"))


def revise_arch_ru(text: str) -> str:
    text = normalize(text)
    text = upsert_managed_block(text, ARCH_BOUNDARY_MARKER, ARCH_BOUNDARIES_RU, "## 4. Терминология")
    text = replace_heading_range(text, r"^## 18\..*$", r"^## 19\..*$", ARCH_ROADMAP_RU)
    text = replace_heading_range(text, r"^## 19\..*$", r"^## 20\..*$", ARCH_GATE_RU)
    return normalize(text.replace("2.3–2.6", "2.3–2.9").replace("2.3-2.6", "2.3–2.9"))


def revise_epic(body: str, cleanup_ref: str) -> str:
    body = normalize(body)
    body = body.replace("IncidentRelay 2.3–2.6", "IncidentRelay 2.3–2.9")
    start = body.find("# IncidentRelay 2.3")
    end = body.find("## Migration policy", start)
    if start < 0 or end < 0:
        raise RuntimeError("Epic #45 release roadmap anchors were not found")
    releases = EPIC_RELEASES.format(cleanup_ref=cleanup_ref)
    body = normalize(body[:start].rstrip() + "\n\n" + releases.strip() + "\n\n---\n\n" + body[end:].lstrip())
    body = body.replace("when added in 2.4", "when added in 2.6")
    body = body.replace("when added in 2.5", "when added in 2.7")
    cleanup_gate = f'''## Final cleanup acceptance additions\n\n- AlertGroup technical comments remain supported after cleanup.\n- Incident operational comments remain separate; comments are not blindly copied.\n- Responders/stakeholders are canonical Incident data after the collaboration cutover.\n- Deprecated AlertGroup responder/stakeholder writes are removed only in 2.9 after reconciliation.\n- Historical Incidents are not created solely for cleanup.\n- Final cleanup is tracked by {cleanup_ref}.'''
    return upsert_managed_block(body, EPIC_CLEANUP_MARKER, cleanup_gate, "## Epic acceptance criteria")


def revise_issue(number: int, body: str) -> str:
    # Remove obsolete #83 interpretation blocks produced by the earlier roadmap
    # script before installing the corrected boundary.
    if number in {47, 48, 49, 55, 59}:
        body = remove_managed_block(body, "incidentrelay-issue-83-roadmap")
    # #49 previously allocated part of #84 to 2.3; that is superseded by 2.4.
    if number == 49:
        body = remove_managed_block(body, "incidentrelay-issue-84-roadmap")

    body = replace_issue_roadmap(body, ISSUE_ALLOCATIONS[number])
    if number == 85:
        body = body.replace("## 2.3 scope", "## 2.4 scope")
        body = body.replace("## Out of scope for the 2.3 subset", "## Out of scope for the 2.4 subset")
        body = body.replace("- notification recovery hysteresis;\n", "")
        body = body.replace("This is not a 2.3 release blocker.", "This is not a 2.4 release blocker.")
    if number in EXTRA_BLOCKS:
        body = upsert_managed_block(
            body, f"incidentrelay-v2-boundary-{number}", EXTRA_BLOCKS[number], "## Dependencies"
        )
    return normalize(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    args = parser.parse_args()
    ensure_environment()
    print("Mode:", "APPLY" if args.apply else "DRY RUN")

    cleanup = find_exact_issue(args.repo, CLEANUP_TITLE)
    if cleanup:
        cleanup_ref = f"#{cleanup['number']}"
        print("Using cleanup workstream", cleanup_ref)
    elif args.apply:
        cleanup = create_cleanup_issue(args.repo)
        cleanup_ref = f"#{cleanup['number']}"
        print("Created cleanup workstream", cleanup_ref)
    else:
        cleanup_ref = "#<new-cleanup-workstream>"
        print("Would create:", CLEANUP_TITLE)

    en_old = ARCH_EN.read_text(encoding="utf-8")
    en_new = revise_arch_en(en_old)
    show_diff(str(ARCH_EN), en_old, en_new)
    if args.apply and normalize(en_old) != normalize(en_new):
        ARCH_EN.write_text(en_new, encoding="utf-8")

    if ARCH_RU.exists():
        ru_old = ARCH_RU.read_text(encoding="utf-8")
        ru_new = revise_arch_ru(ru_old)
        show_diff(str(ARCH_RU), ru_old, ru_new)
        if args.apply and normalize(ru_old) != normalize(ru_new):
            ARCH_RU.write_text(ru_new, encoding="utf-8")

    epic = issue_json(args.repo, 45)
    epic_new = revise_epic(epic.get("body") or "", cleanup_ref)
    show_diff("issue #45", epic.get("body") or "", epic_new)
    if args.apply:
        edit_issue(
            args.repo, 45, epic_new,
            title="[Epic] Incident Management v2: staged delivery across 2.3–2.9"
        )

    for number in [46,47,48,49,50,51,52,53,54,55,59,85]:
        issue = issue_json(args.repo, number)
        old = issue.get("body") or ""
        new = revise_issue(number, old)
        show_diff(f"issue #{number}", old, new)
        if args.apply and normalize(old) != normalize(new):
            edit_issue(args.repo, number, new)
        if args.apply and number == 85:
            cmd("gh", "issue", "edit", "85", "--repo", args.repo, "--add-label", "incident-management-v2")

    upsert_comment(args.repo, 83, COMMENT_83_MARKER, COMMENT_83, args.apply)
    upsert_comment(args.repo, 84, COMMENT_84_MARKER, COMMENT_84, args.apply)
    upsert_comment(args.repo, 60, COMMENT_60_MARKER, COMMENT_60, args.apply)

    if args.apply:
        print("\nApplied. Review local docs with:")
        print("  git diff -- docs/architecture/incident-management-v2.md docs/ru/architecture/incident-management-v2.md")
        print("\nSuggested commit:")
        print('  git add docs/architecture/incident-management-v2.md docs/ru/architecture/incident-management-v2.md')
        print('  git commit -m "docs: expand Incident Management v2 roadmap to 2.9"')
    else:
        print("\nDry-run complete. Re-run with --apply to apply changes.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print("\nCommand failed:", " ".join(exc.cmd), file=sys.stderr)
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        raise
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
