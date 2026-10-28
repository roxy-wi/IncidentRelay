---
title: Service Default Stakeholders
description: Automatically attach service owners as incident stakeholders.
---

# Service default stakeholders

Service default stakeholders let you define users who should automatically be attached to new incidents for a service.

When a new incident is created for a service, IncidentRelay copies active service owners into the incident stakeholder list. This is a snapshot: changing service default stakeholders later does not rewrite existing incidents.

## When default stakeholders are used

Default stakeholders are copied only when an operational Incident is created with a primary service. Creating an AlertGroup, linking an existing Incident to a group, changing its primary service, or adding an affected service does not create a new owner snapshot.

They are useful for:

- service owners
- business owners
- support contacts
- customer success contacts
- executives or other observers

## How it works

A service can have one or more default stakeholders.

Each default stakeholder is stored on the service as a service owner record. When IncidentRelay creates a new incident for this service, active service owners are copied to the incident stakeholder list.

After the copy is done, the incident has its own stakeholder snapshot.

This means:

- new service default stakeholders affect only new incidents
- disabled service default stakeholders are not copied to new incidents
- existing incidents are not changed when service defaults are edited
- stakeholders can be added or deactivated on an existing Incident; its public API does not edit notification flags

## Supported roles

The role field describes why the user is attached to the incident.

Common roles:

| Role | Description |
|---|---|
| `owner` | Technical or operational owner |
| `stakeholder` | General stakeholder |
| `business_owner` | Business owner |
| `support` | Support contact |
| `customer_success` | Customer success contact |
| `executive` | Executive observer |
| `custom` | Custom role |

The role is copied to the incident stakeholder record.

## Notification options

Each default stakeholder has notification flags.

| Flag | Event |
|---|---|
| `notify_on_created` | New incident created |
| `notify_on_priority_change` | Incident priority changed |
| `notify_on_status_change` | Operational Incident workflow status changed |
| `notify_on_resolved` | Operational Incident resolved |
| `notify_on_comment` | Operational Incident comment added |

These flags are copied to the incident stakeholder snapshot together with the user and role.

## Notification channels

Stakeholder notifications are sent through:

- email, when the stakeholder has an email address
- browser push, when the stakeholder is an active IncidentRelay user with browser push enabled

Browser push notifications for stakeholders are informational. They do not include acknowledge, resolve, shelve or unshelve action buttons.

External stakeholders without an IncidentRelay user account can receive email notifications only.

## Incident lifecycle events

The snapshot flags control creation, priority changes, workflow changes,
resolution and operational comments. Technical AlertGroup ACK/resolve and
technical comments do not trigger equivalent Incident events. Resolving a linked
AlertGroup does not automatically resolve the Incident.

Notifications contain the Incident title, priority, workflow status and workspace
URL. The actor is skipped for their own stakeholder notifications. Delivery is
persisted with the event and retried by the existing notification scheduler.
Email and push retry independently; see [delivery guarantees](../incidents/stakeholders.md#delivery-and-retries).

## Existing incidents

Default stakeholder changes affect only new incidents.

Existing incidents keep their own stakeholder snapshot. To change stakeholders for an existing incident, add or deactivate recipients in the Incident stakeholder list.

## API

### List service default stakeholders

```http
GET /api/services/<service_id>/owners
```

Returns default stakeholders configured for the service.

### Create service default stakeholder

```http
POST /api/services/<service_id>/owners
```

Example request:

```json
{
  "user_id": 42,
  "role": "business_owner",
  "active": true,
  "notify_on_created": true,
  "notify_on_priority_change": true,
  "notify_on_status_change": false,
  "notify_on_resolved": true,
  "notify_on_comment": true
}
```

### Update service default stakeholder

```http
PUT /api/services/<service_id>/owners/<owner_id>
```

Example request:

```json
{
  "user_id": 42,
  "role": "support",
  "active": true,
  "notify_on_created": true,
  "notify_on_priority_change": false,
  "notify_on_status_change": true,
  "notify_on_resolved": true,
  "notify_on_comment": true
}
```

### Deactivate service default stakeholder

```http
DELETE /api/services/<service_id>/owners/<owner_id>
```

The delete endpoint deactivates the default stakeholder. Existing incident stakeholders are not changed.

Example response:

```json
{
  "deleted": true,
  "id": 10
}
```
