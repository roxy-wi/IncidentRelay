---
title: Incident Stakeholders
description: Incident stakeholder snapshots, lifecycle notifications and service default stakeholders.
---

# Incident Stakeholders

Incident stakeholders are people who should stay informed about an incident without necessarily being the active responder or assignee.

> **Scope (IncidentRelay 2.3):** stakeholder records on this page are **AlertGroup-scoped** — they attach to the technical alert group that backs the incident. Canonical first-class Incident stakeholders are planned for the 2.5 collaboration stage. The stakeholder notifications described here are technical AlertGroup notifications and are deliberately kept separate from the future operational Incident notification model.

Stakeholders are useful for:

- service owners;
- business owners;
- support contacts;
- customer success contacts;
- executives or other observers.

## Stakeholder snapshots

When an incident is created for a service, IncidentRelay can copy service default stakeholders into the incident stakeholder list.

This is a snapshot:

- new service default stakeholders affect only new incidents;
- existing incidents keep their own stakeholder list;
- incident stakeholders can be edited directly without changing the service defaults.

Read more: [Service default stakeholders](../services/default-stakeholders.md).

## Notification events

Stakeholders can receive notifications for lifecycle events:

| Event | Description |
|---|---|
| Added | The user was added to the incident as a stakeholder. |
| Created | A new incident was created for a service. |
| Priority changed | A responder changed the incident priority manually. |
| Status changed | The incident was acknowledged or changed status. |
| Resolved | The incident was resolved. |

## Added as a stakeholder

When a stakeholder is added to an incident, that stakeholder is notified that they were added. The message includes the incident title, status, severity, priority, team, service and a link to the incident.

Scope and behavior:

- only manually added stakeholders are notified. Stakeholders created automatically from service default stakeholders are not notified on add, so incident creation does not fan out a burst of notifications;
- a user who adds themselves as a stakeholder is not notified;
- a stakeholder added by email address only, with no linked IncidentRelay user, is notified by email only. Slack and browser push are not attempted because there is no profile to look up;
- delivery is asynchronous and persistent: adding the stakeholder enqueues the notification, and a background scheduler delivers it with retries for transient failures. Each channel is tracked independently, so one channel failing does not hide another succeeding;
- a notification failure never prevents the stakeholder from being added.

Timeline events `stakeholder_added_notification_queued`, `stakeholder_added_notification_sent` and `stakeholder_added_notification_failed` record the outcome, including which channels succeeded and any per-channel failures.

This event is separate from the lifecycle notifications above and is not controlled by the `notify_on_*` flags.

## Notification channels

Stakeholder notifications are informational.

They can be delivered through:

- email, when the stakeholder has an email address;
- Slack, when the stakeholder is an active IncidentRelay user with a Slack user ID and the incident has a Slack channel that accepts the incident severity;
- browser push, when the stakeholder is an active IncidentRelay user with browser push enabled.

In Slack Bot API mode the added-as-stakeholder notification is sent as a private direct message, which needs the `im:write` scope. With an incoming-webhook Slack channel a direct message is not possible, and the message is **not** posted to the shared channel by default, to keep the notification private; a channel may opt in with `allow_dm_channel_fallback`. See [Slack](../integrations/slack.md).

Stakeholder browser push notifications do not include ACK, Resolve, Shelve or Unshelve action buttons.

