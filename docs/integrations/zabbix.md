---
title: Zabbix Integration
description: Zabbix incoming alert route setup and payload format.
---

# Zabbix integration

Zabbix is an incoming alert source.

Endpoint:

```text
POST /api/integrations/zabbix
```

Authentication uses a route intake token:

```text
Authorization: Bearer ROUTE_TOKEN
```

## Route setup

Create a route with:

```text
Source: zabbix
```

Attach at least one notification channel and copy the route intake token into the Zabbix media type or webhook configuration.

## Service assignment

After a route matches the incoming alert, IncidentRelay can attach the alert to a service.

There are two ways:

1. Select a default service on the route.
2. Configure service match rules.

Use a default service when all alerts through the route belong to the same system. Use service match rules when one route receives alerts for multiple systems.

Example service match rule:

```json
{
  "labels": {
    "service": "cpu",
    "environment": {
      "op": "regex",
      "value": "^(prod|production)$"
    }
  }
}
```

## Payload example

```json
{
  "status": "firing",
  "event_id": "123456",
  "trigger_id": "98765",
  "event_name": "High CPU load on host1",
  "host": "host1",
  "event_severity": "High",
  "event_status": "PROBLEM",
  "opdata": "CPU load is above 90%",
  "event_tag": "team: infra, service: cpu",
  "tags": [
    {
      "tag": "team",
      "value": "infra"
    },
    {
      "tag": "service",
      "value": "cpu"
    }
  ],
  "event_link": "https://zabbix.example.com/tr_events.php?triggerid=98765&eventid=123456",
  "team": "infra",
  "labels": {
    "host": "host1",
    "service": "cpu",
    "environment": "prod"
  }
}
```

Zabbix media type parameters can use macros:

```json
{
  "event_id": "{EVENT.ID}",
  "trigger_id": "{TRIGGER.ID}",
  "event_name": "{EVENT.NAME}",
  "host": "{HOST.NAME}",
  "event_severity": "{EVENT.SEVERITY}",
  "event_status": "{EVENT.STATUS}",
  "opdata": "{EVENT.OPDATA}",
  "event_tag": "{EVENT.TAGS}",
  "tags": "{EVENT.TAGSJSON}",
  "event_link": "{$ZABBIX.URL}/tr_events.php?triggerid={TRIGGER.ID}&eventid={EVENT.ID}",
  "team": "{EVENT.TAGS.oncall_team}"
}
```

`event_link` is stored in `labels.event_link` and is also exposed as `alert.event_link` in the alert API response. It is used by the alert details modal to open the original Zabbix event.

`event_tag` is stored in `labels.event_tag`. When it contains tag-like data such as `team: infra, service: cpu`, IncidentRelay also extracts individual labels such as `team` and `service`.

## Required payload content

A Zabbix payload should contain enough data to identify and describe an alert.

Empty JSON objects should be rejected by validation.

Useful fields:

```text
event_id
trigger_id
event_name
trigger_name
problem_name
title
subject
message
opdata
event_tag
tags
event_link
fingerprint
```

## Normalized fields

| IncidentRelay field | Source |
|---|---|
| `source` | `zabbix` |
| `team_slug` | `team`, `labels.team`, `labels.oncall_team`, or parsed Zabbix tags |
| `external_id` | `event_id`, `eventid`, `trigger_id`, or `triggerid` |
| `title` | `title`, `subject`, `event_name`, `problem_name`, `trigger_name`, `labels.alertname`, then default title |
| `message` | `message`, `description`, or `opdata` |
| `severity` | normalized from `severity`, `event_severity`, `trigger_severity`, or `labels.severity` |
| `labels` | `labels`, parsed `tags`, parsed `event_tag`, plus helper labels such as `host`, `event_name`, `trigger_name`, `zabbix_severity`, and `event_link` |
| `event_link` | `event_link`, `event_url`, `problem_url`, `trigger_url`, `labels.event_link`, or built from `zabbix_url` and `event_id` |
| `status` | `status` or `event_status`, default `firing` |

Zabbix severity values are normalized for IncidentRelay routing and filtering:

| Zabbix severity | IncidentRelay severity |
|---|---|
| `Disaster` | `critical` |
| `High` | `critical` |
| `Average` | `warning` |
| `Warning` | `warning` |
| `Information` | `info` |
| `Not classified` | `info` |

The original Zabbix severity is kept in `labels.zabbix_severity`.
