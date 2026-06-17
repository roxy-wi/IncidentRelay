---
title: Route Intake Tokens
description: Per-route alert intake tokens and security model.
---

# Route Intake Tokens

Incoming integrations authenticate with route intake tokens.

A token belongs to a route, not to a channel.

```text
Monitoring system -> Integration endpoint -> Route token -> Route -> Service -> Channels
```

## Why tokens belong to routes

A route defines:

- source type, such as `alertmanager`, `zabbix` or `webhook`;
- team;
- rotation;
- optional default service;
- matchers;
- service match rules through alert labels, annotations or payload fields;
- attached notification channels;
- grouping behavior.

The token identifies which route should receive incoming alerts.

Channels only describe where notifications are delivered.

## Service assignment

After the route is selected, IncidentRelay can attach the alert to a service.

Use a route default service when all alerts through the route belong to one logical system.

Use service match rules when one route receives alerts for multiple logical systems.

Example:

```text
Route: alertmanager-prod
Service rule 1: labels.job = RabbitMQ   -> RabbitMQ Cloud
Service rule 2: labels.job = PostgreSQL -> PostgreSQL Prod
Service rule 3: labels.app = billing    -> Billing API
```

## Usage

Use the token in the incoming integration request, for example:

```text
Authorization: Bearer ROUTE_TOKEN
```

Do not put route tokens into notification channel configuration.

## Regeneration

If a route token is lost or exposed, regenerate it from the Routes page and update the monitoring system configuration.

After regeneration, the old token should stop working.
