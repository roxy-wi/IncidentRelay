---
title: LibreNMS Integration
description: Receive LibreNMS API Transport alerts and normalize them into IncidentRelay incidents.
---

# LibreNMS integration

IncidentRelay can receive LibreNMS alerts through the LibreNMS **API Transport** and normalize them into regular IncidentRelay incidents.

LibreNMS API Transport should send a JSON payload to:

```http
POST /api/integrations/librenms
```

The route intake token must belong to an IncidentRelay route with:

```text
source = librenms
```

## Behavior

IncidentRelay normalizes every LibreNMS transport payload into one alert event:

| LibreNMS field | IncidentRelay field |
|---|---|
| `uid`, `alert_uid`, `id`, `alert_id` | `external_id` |
| `fingerprint` | explicit `dedup_key` |
| `title`, `subject`, `rule`, `name` | alert title |
| `message`, `msg`, `description`, `alert_notes` | alert message |
| `state`, `status` | alert status |
| `severity` | alert severity |
| `hostname`, `display`, `sysName` | `hostname` label |
| `device_id` | `device_id` label |
| `team` | IncidentRelay team slug override |
| `event_link`, `event_url`, `alert_url`, `source_url`, `device_url` | external alert link |
| `librenms_url` + `hostname` or `device_id` | generated LibreNMS device link |

## Status mapping

IncidentRelay treats these LibreNMS states/statuses as resolved:

```text
0, ok, clear, cleared, recover, recovery, recovered, resolve, resolved, closed
```

Any other state/status is treated as firing.

Examples:

| LibreNMS state | IncidentRelay status |
|---|---|
| `1` | `firing` |
| `2` | `firing` |
| `alert` | `firing` |
| `0` | `resolved` |
| `ok` | `resolved` |
| `recovered` | `resolved` |

## Severity mapping

| LibreNMS severity | IncidentRelay severity |
|---|---|
| `critical`, `crit`, `error`, `err`, `high` | `critical` |
| `warning`, `warn`, `medium` | `warning` |
| `info`, `informational`, `notice`, `low`, `ok`, `clear`, `normal` | `info` |
| unknown non-empty value | original value |
| empty value | `info` |

## Deduplication

IncidentRelay uses the first available value from this list as `external_id`:

```text
uid, alert_uid, id, alert_id
```

If `fingerprint` is provided, it is used as the explicit dedup key.

If there is no explicit fingerprint, IncidentRelay builds a stable dedup key from:

```text
source=librenms
external_id
hostname
rule/name
device_id
```

For reliable firing/recovery correlation, configure LibreNMS to send the same `uid` or `id` for both alert and recovery events.

## Create IncidentRelay route

Create or update an alert route with source `librenms`.

Example route properties:

```json
{
  "name": "LibreNMS",
  "source": "librenms",
  "team_id": 1,
  "matchers": {},
  "group_by": ["hostname", "rule"],
  "enabled": true
}
```

Copy the route intake token. It will be used in the LibreNMS API Transport `Authorization` header.

## Configure LibreNMS API Transport

In LibreNMS, create an Alert Transport with type **API**.

Recommended settings:

| Setting | Value |
|---|---|
| API Method | `POST` |
| API URL | `https://incidentrelay.example.com/api/integrations/librenms` |
| API Headers | `Authorization=Bearer INCIDENTRELAY_ROUTE_TOKEN` |
| API Headers | `Content-Type=application/json` |
| API Body | JSON body from the example below |

## Recommended API Body

Use a JSON body like this in the LibreNMS API Transport configuration:

```json
{
  "id": "{{ $id }}",
  "uid": "{{ $uid }}",
  "state": "{{ $state }}",
  "severity": "{{ $severity }}",
  "title": "{{ $title }}",
  "message": "{{ $msg }}",
  "hostname": "{{ $hostname }}",
  "display": "{{ $display }}",
  "sysName": "{{ $sysName }}",
  "device_id": "{{ $device_id }}",
  "ip": "{{ $ip }}",
  "os": "{{ $os }}",
  "type": "{{ $type }}",
  "hardware": "{{ $hardware }}",
  "version": "{{ $version }}",
  "location": "{{ $location }}",
  "rule": "{{ $name }}",
  "timestamp": "{{ $timestamp }}",
  "team": "sre",
  "librenms_url": "https://librenms.example.com"
}
```

`team` is optional. Use it only when you want the payload to override routing to a specific IncidentRelay team slug.

`librenms_url` is optional. When it is set, IncidentRelay can generate a LibreNMS device link from `librenms_url` and `hostname` or `device_id`.

## Custom labels

You can attach additional labels with the `labels` object:

```json
{
  "uid": "{{ $uid }}",
  "state": "{{ $state }}",
  "severity": "{{ $severity }}",
  "title": "{{ $title }}",
  "message": "{{ $msg }}",
  "hostname": "{{ $hostname }}",
  "labels": {
    "environment": "prod",
    "service": "network",
    "source_system": "librenms"
  }
}
```

IncidentRelay copies `labels` into the normalized alert labels and also adds normalized LibreNMS labels such as:

```text
hostname
device_id
ip
os
type
hardware
version
location
rule
librenms_id
librenms_uid
librenms_state
librenms_timestamp
librenms_severity
event_link
```

## Example firing payload

```json
{
  "id": "12345",
  "uid": "lnms-alert-12345",
  "state": "1",
  "severity": "critical",
  "title": "Device down",
  "message": "Device router1 is unreachable",
  "hostname": "router1",
  "device_id": "77",
  "ip": "10.0.0.1",
  "rule": "Device down",
  "timestamp": "2026-06-17 10:00:00",
  "team": "sre",
  "librenms_url": "https://librenms.example.com"
}
```

Normalized result:

```json
{
  "source": "librenms",
  "team_slug": "sre",
  "external_id": "lnms-alert-12345",
  "title": "Device down",
  "message": "Device router1 is unreachable",
  "severity": "critical",
  "status": "firing",
  "labels": {
    "hostname": "router1",
    "device_id": "77",
    "ip": "10.0.0.1",
    "rule": "Device down",
    "event_link": "https://librenms.example.com/device/device=router1/"
  }
}
```

## Example recovery payload

Send the same `uid` or `id`, but set `state` to a recovery value:

```json
{
  "id": "12345",
  "uid": "lnms-alert-12345",
  "state": "0",
  "severity": "ok",
  "title": "Device down",
  "message": "Device router1 recovered",
  "hostname": "router1",
  "device_id": "77",
  "rule": "Device down"
}
```

Normalized status:

```json
{
  "status": "resolved"
}
```

## Test with curl

```bash
curl -X POST "https://incidentrelay.example.com/api/integrations/librenms" \
  -H "Authorization: Bearer INCIDENTRELAY_ROUTE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "12345",
    "uid": "lnms-alert-12345",
    "state": "1",
    "severity": "critical",
    "title": "Device down",
    "message": "Device router1 is unreachable",
    "hostname": "router1",
    "device_id": "77",
    "rule": "Device down",
    "team": "sre",
    "librenms_url": "https://librenms.example.com"
  }'
```

Expected response is the same shape as other IncidentRelay incoming alert integrations: the request should be accepted and routed through the matching `librenms` route.

## Troubleshooting

### 401 unauthorized

Check that the `Authorization` header contains the route intake token:

```text
Authorization=Bearer INCIDENTRELAY_ROUTE_TOKEN
```

Also check that the token belongs to a route with:

```text
source = librenms
```

### 400 validation_error

The payload must contain at least one meaningful identity or content field, for example:

```text
id, uid, alert_id, title, name, rule, message, msg, description, hostname, display, sysName, fingerprint or labels
```

### Recovery creates a new incident instead of resolving the old one

Make sure firing and recovery payloads use the same stable identity:

```text
uid or id
```

Do not include changing values such as timestamp in `fingerprint`.

### Event link is missing

Send one of these fields:

```text
event_link, event_url, alert_url, source_url, device_url
```

Or send `librenms_url` together with `hostname` or `device_id` so IncidentRelay can generate a device link.
