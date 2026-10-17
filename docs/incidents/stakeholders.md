---
title: Incident Stakeholders
description: Incident stakeholder snapshots, lifecycle notifications and service default stakeholders.
---

# Incident Stakeholders

> **2.3 boundary:** stakeholder records on this page are still attached to technical AlertGroups. Canonical first-class Incident stakeholders are planned for the 2.5 collaboration stage.


Incident stakeholders are people who should stay informed about an incident without necessarily being the active responder or assignee.

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
- delivery is best-effort: the notification counts as sent when at least one channel succeeds, and per-channel failures are recorded in the incident timeline;
- a notification failure never prevents the stakeholder from being added.

Timeline events `stakeholder_added_notification_sent` and `stakeholder_added_notification_failed` record the outcome, including which channels succeeded and any per-channel errors.

This event is separate from the lifecycle notifications above and is not controlled by the `notify_on_*` flags.

## Notification channels

Stakeholder notifications are informational.

They can be delivered through:

- email, when the stakeholder has an email address;
- Slack, when the stakeholder is an active IncidentRelay user with a Slack user ID and the incident has a Slack channel;
- browser push, when the stakeholder is an active IncidentRelay user with browser push enabled.

In Slack Bot API mode the added-as-stakeholder notification is sent as a direct message, which needs the `im:write` scope. With an incoming-webhook Slack channel the message is posted to the configured channel with the user mentioned instead. See [Slack](../integrations/slack.md).

Stakeholder browser push notifications do not include ACK, Resolve, Shelve or Unshelve action buttons.

