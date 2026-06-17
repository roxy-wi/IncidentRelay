---
title: Demo Data
description: Create and verify IncidentRelay demo data for local testing.
---

# Demo Data

Use demo data only for local testing and development.

Typical demo setup creates:

- a group;
- users;
- a team;
- a rotation;
- services;
- service links and runbooks;
- route and channels;
- route intake tokens;
- example alerts.

Do not use demo passwords, tokens or webhook URLs in production.

## Services in demo data

If demo data creates services, use them to test:

- default route service assignment;
- service match rules;
- links in alert context;
- runbooks in alert notifications;
- service dependencies;
- service analytics and impact views.

Recommended demo service examples:

```text
Service: RabbitMQ Cloud
Slug: rabbitmq-cloud
Type: queue
Environment: production
Criticality: critical

Service: Billing API
Slug: billing-api
Type: api
Environment: production
Criticality: high

Service: PostgreSQL Prod
Slug: postgresql-prod
Type: database
Environment: production
Criticality: critical
```

Recommended demo link examples:

```text
Grafana dashboard
Logs
Repository
Documentation
```

Recommended demo runbook examples:

```text
Generic service troubleshooting
RabbitMQ cluster partition
Database connection errors
```

If demo data does not include services yet, create a service manually from the Services page to test service links, runbooks and impact views.
