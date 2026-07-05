---
title: Alerts and Alert Groups
description: Alert group lifecycle, grouping, comments and API examples.
---

# Alerts and alert groups

IncidentRelay stores every incoming monitoring signal as an **alert** and shows operators an **alert group** in the Alerts page.

An alert group is the incident-level object. It is the object that users acknowledge, resolve, notify, remind, escalate, and merge.

A child alert is the concrete signal inside the group. For example, three `DiskFull` alerts from three hosts can be shown as one alert group with three child alerts.

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

If a new child alert arrives in an acknowledged group, IncidentRelay reopens the group as `firing`. This makes new signal visible again and prevents important new data from being hidden behind an old acknowledgement.

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

## Manual incidents

Manual incidents allow responders and editors to create an incident directly from the UI or API when the problem is known before an external monitoring system sends an alert.

A manual incident is stored as a normal alert group with one child alert:

- alert group `source` is `manual`;
- child alert `source` is `manual`;
- status starts as `firing`;
- acknowledge, resolve, responders, stakeholders, comments, priority and timeline work the same way as for integration-created alert groups.

Manual incidents do not require an intake route. The creator selects the team directly, and may optionally select a service.

If a service is selected, IncidentRelay can use the service ownership, default rotation, escalation policy and notification policy. Route channels are not used for route-less manual incidents.

### Permissions

A user may create a manual incident for a team when they are one of:

- global admin;
- group editor or group admin for the team group;
- team manager;
- team responder.

Viewers cannot create manual incidents.

### API example

```bash
curl -X POST https://incidentrelay.example.com/api/incidents \
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

When notifying is true, IncidentRelay schedules the normal alert group notification. For route-less manual incidents, delivery is resolved through the selected service notification policy.

If no service is selected, or the selected service has no matching notification policy rule, the incident is still created but no notification target may be found.

## Manual merge

Manual merge is useful when two groups were created separately but actually describe one incident.

The UI can merge selected alert groups. The target is the group that remains visible. Child alerts from other groups are moved into the target group.

API example:

```bash
curl -X POST https://incidentrelay.example.com/api/alerts/merge \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target_group_id": 101,
    "source_group_ids": [102, 103],
    "reason": "Same customer-facing incident"
  }'
```

Response is the target alert group with recalculated counters.

## API compatibility

The Alerts API path remains:

```text
/api/alerts
```

For compatibility with the existing UI and clients, response items are still returned from `/api/alerts`, but each item is now an alert group.

The `id` field in `/api/alerts` responses is the alert group id.

Details are available at:

```text
GET /api/alerts/{alert_id}
```

The path parameter name is kept as `alert_id` for compatibility, but it should be treated as an alert group id.

## API examples

### List groups

```bash
curl -H "Authorization: Bearer TOKEN" \
  "https://incidentrelay.example.com/api/alerts?status=firing&severity=critical"
```

### Get group details

```bash
curl -H "Authorization: Bearer TOKEN" \
  "https://incidentrelay.example.com/api/alerts/101"
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
curl -X POST https://incidentrelay.example.com/api/alerts/101/ack \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Resolve group

```bash
curl -X POST https://incidentrelay.example.com/api/alerts/101/resolve \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Troubleshooting

### Alerts are not grouped

Check the route `group_by` value. If `instance`, `pod`, `container`, or another high-cardinality label is included, IncidentRelay may create one group per host or per pod.

### Unrelated alerts are grouped

Add more fields to route `group_by`, such as `instance`, `mountpoint`, `service`, or another label that separates incidents for the team.

### The group was acknowledged but became firing again

A new child alert arrived in the acknowledged group. IncidentRelay reopens acknowledged groups when new child alerts arrive so the new signal is visible.

### A resolved notification was not sent

If the group resolved before the first delayed notification was sent, IncidentRelay intentionally skips both firing and resolved notifications to avoid noise.

### A group disappeared after merge

The source group was marked as `merged`. Open the target group to see moved child alerts.
