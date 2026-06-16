# Service default stakeholders

Service default stakeholders let you define users who should automatically be attached to new incidents for a service.

When a new incident is created for a service, IncidentRelay copies active service owners into the incident stakeholder list. This is a snapshot: changing service default stakeholders later does not rewrite existing incidents.

## When default stakeholders are used

Default stakeholders are copied when a new alert group / incident is created and matched to a service.

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
- incident stakeholders can still be edited directly on the incident

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
| `notify_on_status_change` | Incident acknowledged or status changed |
| `notify_on_resolved` | Incident resolved |

These flags are copied to the incident stakeholder snapshot together with the user and role.

## Notification channels

Stakeholder notifications are sent through:

- email, when the stakeholder has an email address
- browser push, when the stakeholder is an active IncidentRelay user with browser push enabled

Browser push notifications for stakeholders are informational. They do not include acknowledge or resolve action buttons.

External stakeholders without an IncidentRelay user account can receive email notifications only.

## Incident lifecycle events

Default stakeholders can receive notifications for the following lifecycle events.

### New incident created

When a new alert group is created for a service, IncidentRelay copies active service owners to incident stakeholders.

If `notify_on_created` is enabled, the stakeholder receives an email and, when available, a browser push notification.

### Priority changed

When incident priority is changed manually, stakeholders with `notify_on_priority_change` enabled are notified.

The notification includes the old and new priority.

### Status changed

When an incident is acknowledged or its status changes, stakeholders with `notify_on_status_change` enabled are notified.

Manual acknowledge sends a status change notification.

### Incident resolved

When an incident is resolved manually or by an incoming resolved payload from an integration, stakeholders with `notify_on_resolved` enabled are notified.

Repeated resolved payloads do not send duplicate stakeholder notifications if the incident was already resolved.

## Existing incidents

Default stakeholder changes affect only new incidents.

Existing incidents keep their own stakeholder snapshot. To change stakeholders for an existing incident, edit the incident stakeholder list directly.

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
  "notify_on_resolved": true
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
  "notify_on_resolved": true
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

## Recommended documentation index link

Add this link to the Services section in `docs/index.md`:

```md
- [Service default stakeholders](services/default-stakeholders.md)
```
