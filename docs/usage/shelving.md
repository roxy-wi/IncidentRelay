---
title: Alert Shelving
description: Temporarily pause notification and escalation for one AlertGroup without changing technical status.
---

# Alert shelving

Shelving temporarily removes one existing AlertGroup from the responder attention cycle without changing the technical truth of the alert.

A shelved AlertGroup remains `firing` or `acknowledged`. IncidentRelay continues ingesting child alerts, recording events, correlating signals and calculating service/business impact, but pauses active notification work until the shelf ends.

## Shelve versus other controls

| Control | Meaning |
| --- | --- |
| Acknowledge | A responder has taken ownership of the alert. |
| Shelve | Pause attention for this one existing AlertGroup and return to it later. |
| Silence | Suppress alerts matching a rule/matcher, including other matching groups. |
| Maintenance | Planned, scoped suppression for services/teams during maintenance. |
| Resolve | The technical problem is no longer active. |

Shelving is intentionally not a new AlertGroup status.

## What is paused

While a shelf is active IncidentRelay suppresses:

- initial/group notifications;
- queued alert updates;
- reminders;
- escalation deliveries;
- pending user notification deliveries for those lifecycle events.

Incident ingestion and technical state continue normally.

## What continues

Shelving does not stop:

- new child-alert ingestion;
- source status updates;
- event history;
- correlation;
- service and business impact calculation;
- source-driven or manual resolution.

If the AlertGroup resolves while shelved, the shelf is closed and no later expiry reactivates it.

## Web UI

Open Alert Details and choose **Shelve**. Select a duration (30 minutes, 1, 2, 4, 8 or 24 hours) and optionally enter a reason.

Use **Unshelve** to return early. The Alerts page also provides **Shelved only** filtering.

## Notification actions

Interactive notifications expose the same AlertGroup action:

- Telegram: **Shelve 1h** / **Unshelve**;
- Slack Bot API: **Shelve 1h** / **Unshelve**;
- Mattermost Bot API: **Shelve 1h** / **Unshelve**;
- Browser Push: one-click **Shelve 1h**; the confirmation notification provides **Unshelve** and **Resolve** for the active shelf.

External actions require a linked IncidentRelay user and normal responder permissions for the AlertGroup team.

## Expiry and resume behavior

When a shelf expires or is manually removed:

- if the group is still `firing`, IncidentRelay queues one current-state notification and restarts escalation from the unshelve time;
- if the group is `acknowledged`, it stays acknowledged and no firing escalation is restarted;
- if the group is already `resolved`, nothing is reactivated.

## API

```http
POST /api/alerts/{alert_group_id}/shelve
Content-Type: application/json
```

```json
{
  "duration_seconds": 3600,
  "reason": "Waiting for deployment"
}
```

To end a shelf:

```http
POST /api/alerts/{alert_group_id}/unshelve
```

List only currently shelved groups with:

```text
GET /api/alerts?shelved=1
```

The serialized AlertGroup keeps its normal `status` and adds `shelved` plus the current `shelve` object.

## Scheduler settings

```ini
[alerts]
shelve_lifecycle_check_interval_seconds = 30
shelve_lifecycle_batch_size = 100
```

The scheduler expires due shelves in bounded batches. Run the IncidentRelay scheduler in production installations that use timed shelving.

## Audit and timeline

Shelve, unshelve and automatic expiry create AlertGroup events and audit records. The source records whether the action came from the UI, Telegram, Slack, Mattermost, Browser Push or the scheduler.
