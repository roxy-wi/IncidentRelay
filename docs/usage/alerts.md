---
title: Alerts and Alert Groups
description: Alert group lifecycle, grouping, comments and API examples.
---

# Alerts and alert groups

IncidentRelay stores every incoming monitoring signal as an **alert** and shows operators an **alert group** in the Alerts page.

An alert group is the incident-level object. It is the object that users acknowledge, resolve, temporarily shelve, notify, remind, escalate, and merge.

A child alert is the concrete signal inside the group. For example, three `DiskFull` alerts from three hosts can be shown as one alert group with three child alerts.

## Personal filters on the dashboard

The active alerts card has **My alerts / All alerts** buttons. **My alerts** shows alert groups assigned to you, or linked to an Incident where you are a responder or an active stakeholder. **Filters** opens the involvement selector and the existing service filter. Select several services to include any of them; service, involvement and the global Team selector are combined using AND.

These personal filters affect only the active alerts table. Dashboard totals, charts, system status and service health keep the global team scope. **View all** opens Alerts with the same team, services, involvement and active statuses (`firing` and `acknowledged`). **Reset** clears personal filters without changing the global Team selector. Changing team or active group refreshes the service options and removes incompatible selections.

Involvement and selected services are shared between Dashboard and Alerts, including navigation through the sidebar. They survive a reload and are stored in this browser separately for each user and active group. Alerts keeps its own status, severity, priority, search and pagination settings. Links containing explicit filters take precedence over saved preferences; Back/Forward restores the selection recorded in that history entry. Resetting Dashboard clears the shared filters on both pages.

The Alerts page also exposes **Involvement**. The API accepts `GET /api/alert-groups?involvement=any` (choose one value):

- `assigned`: the alert group's assignee is the current user.
- `responder`: a linked Incident has a responder request targeting the user or accepted by them, with status `requested`, `accepted` or `resolved`. An unaccepted team request does not include every team member.
- `stakeholder`: the user has an active stakeholder subscription to a linked Incident.
- `any`: any of the above, without duplicate alert groups.

Removed Incident links do not count. Closed Incidents can still provide membership when searching historical alert groups. Personal filters never expand team access; without a user identity they return no groups. Existing `assigned_to_me=true` requests still work; if both parameters are supplied, their conditions are combined using AND.

## Main terms

| Term | Meaning |
| --- | --- |
| Alert group | Incident-level object shown on the Alerts page. |
| Child alert | Concrete incoming signal inside an alert group. |
| `dedup_key` | Identifies one concrete alert and is used to update the same child alert. |
| `group_key` | Identifies which child alerts belong to the same alert group. |
| `group_by` | Route setting that controls which fields are used to build `group_key`. |
| Merge | Manual operation that moves child alerts from one group into another group. |

## Deduplication vs grouping

Deduplication and grouping solve different problems.

`dedup_key` updates the same concrete alert. If the same alert is received again with the same `dedup_key`, IncidentRelay updates the existing child alert instead of creating a new child alert.

`group_key` joins several related child alerts into one alert group. If two alerts have different `dedup_key` values but the same `group_key`, they become different child alerts inside the same alert group.

Example:

```json
{
  "labels": {
    "alertname": "DiskFull",
    "severity": "critical",
    "instance": "host1"
  },
  "fingerprint": "disk-full-host1-var"
}
```

and:

```json
{
  "labels": {
    "alertname": "DiskFull",
    "severity": "critical",
    "instance": "host2"
  },
  "fingerprint": "disk-full-host2-var"
}
```

With route `group_by = ["alertname", "severity"]`, both alerts are placed into the same group because they share `alertname=DiskFull` and `severity=critical`.

With route `group_by = ["alertname", "severity", "instance"]`, they are placed into different groups because `instance` differs.

## Default grouping

If a route does not define `group_by`, IncidentRelay uses the default grouping:

```text
alertname
severity
```

The group key is also scoped by source, team, route, and service. This prevents unrelated routes or services from accidentally merging into the same group even when labels look similar.

## Configuring route `group_by`

Route `group_by` accepts a list of field names.

Recommended examples:

```json
["alertname", "severity"]
```

Group by alert name and severity. This is useful for host fan-out alerts where many hosts report the same problem.

```json
["alertname", "severity", "instance"]
```

Group by alert name, severity, and instance. This keeps each host in a separate group.

```json
["alertname", "severity", "mountpoint"]
```

Group disk alerts by mountpoint while still allowing several instances to be combined if that is expected by the team.

Supported field forms:

| Form | Example | Meaning |
| --- | --- | --- |
| Plain label name | `alertname` | Reads from labels first, then annotations, then top-level alert data. |
| Explicit label path | `labels.instance` | Reads from alert labels. |
| Explicit annotation path | `annotations.summary` | Reads from alert annotations. |
| Explicit payload path | `payload.trigger.id` | Reads from normalized payload. |
| Built-in scope | `source`, `team`, `route`, `service` | Uses routed IncidentRelay metadata. |

## Alert group lifecycle

### Firing

A new group starts as `firing` when at least one child alert is firing.

If another child alert is added to the same group, counters are recalculated and the group remains `firing`.

### Acknowledged

Acknowledging an alert group marks the group as `acknowledged`.

Child alerts are not individually acknowledged. This is intentional: the operator acknowledges the incident-level group, not every raw monitoring signal.

Acknowledgement also cancels queued `notification`, `reminder`, and `escalation` deliveries that were scheduled before the ACK. Workers re-check persisted group status before sending firing-only notifications, so stale scheduler state does not page an already acknowledged incident.

A new child alert normally reopens an acknowledged group as `firing`. There is one correlation-specific exception: when the route groups **only** by a non-empty `incident_key` (or `labels.incident_key`), a new child with the same key preserves `acknowledged` if it cannot raise the effective incident priority. A genuine priority increase still reopens the group and starts a fresh escalation cycle.

### Resolved

Resolving an alert group resolves all child alerts in the group.

When incoming resolved payloads are received for existing child alerts, the group is resolved only when all child alerts are resolved.

An orphan resolved payload does not create a new group.

## Comments

Alert details include a Comments section for responder notes.

Comments can be used for investigation context, handover notes, mitigation details, links to dashboards or tickets, and post-resolution follow-up.

Read more: [Alert comments](alert-comments.md).

### Merged

A merged source group is marked as `merged` and points to the target group. Child alerts from the source group are moved into the target group.

Merged groups are hidden from the normal alert list unless the API/UI explicitly asks to include them.

## Group notifications

Alert groups support delayed and batched notifications.

The first firing notification can be delayed by `ALERT_GROUP_WAIT_SECONDS`. This gives IncidentRelay time to collect several child alerts into one group before notifying users.

Updates after the first notification are rate-limited by `ALERT_GROUP_INTERVAL_SECONDS`.

If a group resolves before the first notification is sent, IncidentRelay clears the pending firing notification and does not send noisy stale notifications.

If a group was already notified and then resolves, IncidentRelay sends the resolved notification immediately.

Relevant settings:

```ini
[alerts]
alert_group_wait_seconds = 30
alert_group_interval_seconds = 300
alert_group_notification_check_interval_seconds = 10
alert_group_notification_batch_size = 100
```

## Manual AlertGroups

Manual AlertGroups allow responders and editors to create a technical alert episode directly from the UI or API when a problem is known before an external monitoring system sends an alert.

A manual AlertGroup is stored as one technical AlertGroup with one child Alert:

- alert group `source` is `manual`;
- child alert `source` is `manual`;
- status starts as `firing`;
- acknowledge, resolve, shelving, responders, stakeholders, comments, priority and timeline work the same way as for integration-created alert groups.

Manual AlertGroups do not require an intake route. The creator selects the team directly, and may optionally select a service.

If a service is selected, IncidentRelay can use the service ownership, default rotation, escalation policy and notification policy. Route channels are not used for route-less manual AlertGroups.

### Permissions

A user may create a manual AlertGroup for a team when they are one of:

- global admin;
- group editor or group admin for the team group;
- team manager;
- team responder.

Viewers cannot create manual AlertGroups.

### API example

```bash
curl -X POST https://incidentrelay.example.com/api/alert-groups \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "team_id": 12,
    "service_id": 34,
    "title": "Storage API is unavailable",
    "message": "Customers are receiving 5xx from storage-api.",
    "severity": "critical",
    "priority": "p1",
    "notify": true
  }'
```

Notification behavior

When notifying is true, IncidentRelay schedules the normal alert group notification. For route-less manual AlertGroups, delivery is resolved through the selected service notification policy.

If no service is selected, or the selected service has no matching notification policy rule, the AlertGroup is still created but no notification target may be found.

## Manual merge

Manual merge is useful when two groups were created separately but actually describe one incident.

The UI can merge selected alert groups. The target is the group that remains visible. Child alerts from other groups are moved into the target group.

API example:

```bash
curl -X POST https://incidentrelay.example.com/api/alert-groups/101/merge \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_group_ids": [102, 103],
    "reason": "Same customer-facing incident"
  }'
```

Response is the target alert group with recalculated counters.

## AlertGroup API

IncidentRelay 2.3 exposes technical AlertGroups only under `/api/alert-groups`. The old `/api/alerts` path is removed as part of the intentional 2.3 breaking API split.

The `id` field is always an AlertGroup id. Details are available at:

```text
GET /api/alert-groups/{id}
```

See [IncidentRelay 2.3 API migration](../incidents/api-migration-2.3.md) for the complete endpoint mapping.

## API examples

### List groups

```bash
curl -H "Authorization: Bearer TOKEN" \
  "https://incidentrelay.example.com/api/alert-groups?status=firing&severity=critical"
```

### Get group details

```bash
curl -H "Authorization: Bearer TOKEN" \
  "https://incidentrelay.example.com/api/alert-groups/101"
```

The detail response contains:

```json
{
  "type": "alert_group",
  "id": 101,
  "status": "firing",
  "alert_count": 2,
  "firing_count": 2,
  "alerts": [
    {
      "type": "alert",
      "id": 501,
      "status": "firing",
      "dedup_key": "disk-full-host1-var"
    },
    {
      "type": "alert",
      "id": 502,
      "status": "firing",
      "dedup_key": "disk-full-host2-var"
    }
  ]
}
```

### Acknowledge group

```bash
curl -X POST https://incidentrelay.example.com/api/alert-groups/101/acknowledge \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Resolve group

```bash
curl -X POST https://incidentrelay.example.com/api/alert-groups/101/resolve \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Alert analytics

Open **Alerts → Alert analytics** and select a team and a 7, 30 or 90 day period.

- **Compared with the previous period** compares adjacent windows of equal length. Selecting 7 days compares the last 7 days with the 7 days immediately before them. Values show absolute and percentage changes. ACK rate changes are percentage points. When the previous value is zero, there is no percentage baseline.
- **When alert groups start** shows new groups by weekday and hour. Choose a timezone using the selector. Values are totals over the period. DST is respected: both occurrences of a repeated local hour contribute to the same cell.
- **Largest increases in alert noise** compares saved child-alert occurrences by exact name, ranked by absolute increase. Repeated webhook updates to an existing child alert are not separate occurrences. Zero in the previous window does not necessarily mean a new alert rule.

Click a period value, a non-empty heatmap cell, an alert name or an occurrence count. **Matching alert groups** opens on the same page with the exact period, team, name and local-hour selection, and pagination. Click a group title to open its detail page. Several occurrences can belong to one group; the occurrence column counts only matches within the selected period. A message explains occurrences with no accessible parent group.

MTTA/MTTR use eligible groups created in the window with ACK/resolution before its end. The sample size is shown. Currently maintenance- or orchestration-suppressed groups are excluded from response metrics. Open-now counters are not compared with a historical value.

Windows include their start and exclude their end: `[since, until)`. Calculations use retained records and their currently saved lifecycle timestamps, not historical snapshots. Reopening, merging and retention cleanup can change past results. A short history or small sample limits comparisons. Selection is a fresh read: records may change after a chart was loaded.

`GET /api/alert-groups/analytics?days=7&timezone=Europe%2FMoscow` adds `comparison`, `heatmap` and `noise_growth` to the existing response. `GET /api/alert-groups/analytics/selection` takes the returned `since`/`until`, `metric`, optional `team_id`, exact `alertname` for occurrences, or `weekday` (Monday = 0), `hour` and `timezone` for new groups. It supports `page` and `page_size` (1–100), with a maximum window of 365 days and the same access checks.

## Troubleshooting

### Alerts are not grouped

Check the route `group_by` value. If `instance`, `pod`, `container`, or another high-cardinality label is included, IncidentRelay may create one group per host or per pod.

### Unrelated alerts are grouped

Add more fields to route `group_by`, such as `instance`, `mountpoint`, `service`, or another label that separates incidents for the team.

### The group was acknowledged but became firing again

A new child alert normally reopens the acknowledged group. If the route groups only by `incident_key`, same-key children preserve ACK unless they can raise effective incident priority. If such a group reopened, check whether the incoming child had a higher priority, the key was empty/different, grouping used additional fields, or orchestration overrode the group key.

### A resolved notification was not sent

If the group resolved before the first delayed notification was sent, IncidentRelay intentionally skips both firing and resolved notifications to avoid noise.

### A group disappeared after merge

The source group was marked as `merged`. Open the target group to see moved child alerts.

## Shelving

A responder can temporarily shelve one open AlertGroup without changing `firing`/`acknowledged` technical status. Shelving pauses notification/update/reminder/escalation work, while ingestion and impact calculation continue. See [Alert shelving](shelving.md).
