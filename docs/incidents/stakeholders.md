---
title: Incident Stakeholders
description: Incident stakeholder snapshots, lifecycle notifications and service default stakeholders.
---

# Incident Stakeholders

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
| Created | A new incident was created for a service. |
| Priority changed | A responder changed the incident priority manually. |
| Status changed | The incident was acknowledged or changed status. |
| Resolved | The incident was resolved. |

## Notification channels

Stakeholder notifications are informational.

They can be delivered through:

- email, when the stakeholder has an email address;
- browser push, when the stakeholder is an active IncidentRelay user with browser push enabled.

Stakeholder browser push notifications do not include ACK or Resolve action buttons.

