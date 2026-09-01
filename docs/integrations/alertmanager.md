---
title: Alertmanager Integration
description: Prometheus Alertmanager route setup and payload handling.
---

# Alertmanager integration

Alertmanager is an incoming alert source.

Endpoint:

```text
POST /api/integrations/alertmanager
```

Authentication uses a route intake token:

```text
Authorization: Bearer ROUTE_TOKEN
```

## Route setup

Create a route with:

```text
Source: alertmanager
```

Attach at least one notification channel and copy the route intake token into Alertmanager webhook configuration.


## Alertmanager configuration example

A minimal `alertmanager.yml` receiver can send both firing and resolved notifications directly to IncidentRelay:

```yaml
route:
  receiver: incidentrelay
  group_by:
    - alertname
    - cluster
    - service
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: incidentrelay
    webhook_configs:
      - url: https://incidentrelay.example.com/api/integrations/alertmanager
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/incidentrelay-route-token
```

The credentials file must contain only the IncidentRelay route token, without the `Bearer ` prefix. Keeping the token in a mounted secret file is preferred over committing it to `alertmanager.yml`.

For a small test installation, the token can also be configured inline:

```yaml
receivers:
  - name: incidentrelay
    webhook_configs:
      - url: https://incidentrelay.example.com/api/integrations/alertmanager
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials: ROUTE_TOKEN
```

`send_resolved: true` is important. Without resolved notifications, IncidentRelay cannot automatically close the corresponding alert when Alertmanager reports recovery.

If only part of the Alertmanager tree should go to IncidentRelay, route that subset to the receiver instead of making it the default receiver:

```yaml
route:
  receiver: default-receiver
  routes:
    - receiver: incidentrelay
      matchers:
        - team="infra"
        - environment="production"
```

After changing the configuration, validate it before reloading Alertmanager:

```bash
amtool check-config /etc/alertmanager/alertmanager.yml
```

## Service assignment

After a route matches the incoming alert, IncidentRelay can attach the alert to a service.

There are two ways:

1. Select a default service on the route.
2. Configure service match rules.

Use a default service when all alerts through the route belong to the same system. Use service match rules when one route receives alerts for multiple systems.

Example service match rule for RabbitMQ:

```json
{
  "labels": {
    "job": "RabbitMQ",
    "rabbitmq": {
      "op": "regex",
      "value": "^rabbitmq-cloud$"
    }
  }
}
```

This can attach matching alerts to the `RabbitMQ Cloud` service.

## Payload example

```json
{
  "status": "firing",
  "externalURL": "https://alertmanager.example.com",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "RabbitMQClusterPartition",
        "severity": "critical",
        "instance": "rabbit-1",
        "team": "infra",
        "job": "RabbitMQ",
        "rabbitmq": "rabbitmq-cloud"
      },
      "annotations": {
        "summary": "RabbitMQ cluster partition detected",
        "description": "Erlang distribution link is not healthy",
        "event_link": "https://grafana.example.com/d/rabbitmq/rabbitmq?viewPanel=12",
        "runbook_url": "https://wiki.example.com/runbooks/rabbitmq-cluster-partition"
      },
      "generatorURL": "https://prometheus.example.com/graph?g0.expr=erlang_vm_dist_node_state",
      "fingerprint": "rabbitmq-cloud-partition-rabbit-1"
    }
  ]
}
```

`generatorURL` is the standard Alertmanager source link to the expression that generated the alert. IncidentRelay uses it as `event_link` when a more specific link is not provided in annotations.

IncidentRelay also supports these annotation aliases for the source event link:

```text
event_link
event_url
alert_url
source_url
dashboard_url
panel_url
runbook_url
```

The first non-empty value is stored in `labels.event_link` and exposed as `alert.event_link` in the alert API response.

## Grafana Alerting compatibility

Grafana-managed alert webhooks can include fields such as `dashboardURL`, `panelURL`, and `silenceURL`.

`dashboardURL` and `panelURL` can be used as source-event links. `silenceURL` is not used as `event_link`, because it points to a silence action rather than the original event or dashboard. If present, it should be stored separately as `labels.silence_url`.

## Normalized fields

| IncidentRelay field | Source |
|---|---|
| `source` | `alertmanager` |
| `team_slug` | `labels.team`, `labels.oncall_team`, or top-level `team` |
| `external_id` | `fingerprint` or `labels.alertname` |
| `title` | `annotations.summary`, then `labels.alertname` |
| `message` | `annotations.description` or `annotations.message` |
| `severity` | `labels.severity` |
| `labels` | alert item labels plus helper labels such as `event_link`, `generator_url`, and `alertmanager_url` |
| `event_link` | `annotations.event_link`, `annotations.event_url`, `annotations.alert_url`, `annotations.source_url`, `annotations.dashboard_url`, `annotations.panel_url`, `annotations.runbook_url`, `generatorURL`, `dashboardURL`, or `panelURL` |
| `status` | item status or top-level status, default `firing` |

## Resolve events

Use the same fingerprint and grouping data for resolved events.

That lets IncidentRelay update the existing alert instead of creating a new one.
