---
title: Sentry Integration
description: Signed Sentry issue, metric alert and lifecycle webhooks.
---

# Sentry integration

IncidentRelay can receive signed webhooks from Sentry Internal Integrations and turn Sentry issue alerts, metric alerts and issue lifecycle events into IncidentRelay alerts.

The Sentry integration is route-scoped: every Sentry route has its own webhook URL and its own Sentry webhook secret. The secret is stored in the route integration settings and is never returned by the API.

## Supported Sentry events

IncidentRelay supports the following Sentry webhook resources:

| Sentry resource | Typical action | IncidentRelay status | Notes |
| --- | --- | --- | --- |
| `event_alert` | `triggered` | `firing` | Issue alert rule action fired. |
| `metric_alert` | `critical` | `firing` | Metric alert entered critical state. |
| `metric_alert` | `warning` | `firing` | Metric alert entered warning state. |
| `metric_alert` | `resolved` | `resolved` | Metric alert recovered. |
| `issue` | `created` | `firing` | Issue lifecycle event. |
| `issue` | `unresolved` | `firing` | Issue reopened or regressed. |
| `issue` | `resolved` | `resolved` | Issue was resolved in Sentry. |
| `issue` | `ignored` | `resolved` | Issue was ignored or archived in Sentry. |

For issue alerts, IncidentRelay uses the Sentry issue id as the deduplication key. This allows a later `issue.resolved` event to resolve the same IncidentRelay alert that was created by `event_alert.triggered`.

## Before you start

You need:

- an IncidentRelay team and route management permissions;
- a public HTTPS URL for IncidentRelay that Sentry can reach;
- Sentry organization admin or manager permissions to create an Internal Integration;
- the full Sentry integration implementation deployed, including the `integration_config` migration.

Do not use the legacy Sentry Webhook Plugin for this integration. Use a Sentry Internal Integration because IncidentRelay verifies the `Sentry-Hook-Signature` header sent by Internal Integration webhooks.

## Step 1: Create a Sentry route in IncidentRelay

Open **Routes** and create a new route:

| Field | Recommended value |
| --- | --- |
| Name | `Sentry Backend`, `Sentry Frontend`, or another clear name |
| Source | `Sentry` |
| Team | The team that should own Sentry alerts |
| Service | Optional, but recommended |
| Group by | `[
"project_slug",
"issue_id"
]` for issue alerts |
| Matchers | Optional labels matcher, for example by project or environment |
| Enabled | On |

Example matchers:

```json
{
  "labels": {
    "project_slug": "backend-api",
    "environment": "production"
  }
}
```

Recommended group by for issue alerts:

```json
["project_slug", "issue_id"]
```

Recommended group by for metric alerts:

```json
["project_slug", "sentry_alert_id"]
```

After the route is created, IncidentRelay shows a webhook URL similar to:

```text
https://incidentrelay.example.com/api/integrations/sentry/42
```

Copy this URL. You will paste it into Sentry.

At this stage the route can exist without a Sentry secret. Incoming Sentry webhooks will be rejected until the secret is configured.

## Step 2: Create a Sentry Internal Integration

In Sentry, open organization settings and create an Internal Integration.

Configure:

| Sentry setting | Value |
| --- | --- |
| Name | `IncidentRelay` or a route-specific name such as `IncidentRelay Backend` |
| Webhook URL | The URL copied from IncidentRelay, for example `https://incidentrelay.example.com/api/integrations/sentry/42` |
| Alert Rule Action | Enabled |

Enable webhook resources needed by your alerting flow:

- `event_alert` for Sentry issue alert rules;
- `metric_alert` for Sentry metric alert rules and metric recovery events;
- `issue` for resolve, ignored and reopened lifecycle events.

Save the Sentry Internal Integration.

## Step 3: Copy the Sentry Client Secret into IncidentRelay

After creating the Internal Integration, Sentry shows integration credentials.

Copy the **Client Secret** and paste it into the IncidentRelay route:

1. Open the Sentry route in IncidentRelay.
2. Click **Edit**.
3. Paste the value into **Sentry webhook secret**.
4. Save the route.

IncidentRelay stores the secret in `route.integration_config.sentry.webhook_secret` and uses it to verify incoming webhooks.

The API will only expose:

```json
{
  "integration_config": {
    "sentry": {
      "has_webhook_secret": true,
      "webhook_path": "/api/integrations/sentry/42"
    }
  }
}
```

It will not return the raw secret.

## Step 4: Add IncidentRelay to Sentry alert rules

Create or edit Sentry alert rules.

For issue alerts:

1. Open the Sentry project.
2. Go to **Alerts**.
3. Create or edit an issue alert rule.
4. In the actions section, select the IncidentRelay integration action.
5. Save the rule.

For metric alerts:

1. Open the Sentry project.
2. Go to **Alerts**.
3. Create or edit a metric alert rule.
4. Select the IncidentRelay integration action.
5. Save the rule.

When a Sentry alert rule fires, Sentry sends a signed webhook to IncidentRelay. IncidentRelay verifies the signature and normalizes the event into an internal alert.

## How routing works

Sentry events are normalized with `source=sentry` and labels such as:

```json
{
  "alertname": "SentryIssueAlert",
  "sentry_resource": "event_alert",
  "sentry_action": "triggered",
  "organization_slug": "acme",
  "project_slug": "backend-api",
  "project_name": "Backend API",
  "issue_id": "12345",
  "issue_short_id": "BACKEND-1",
  "event_id": "event-abc",
  "environment": "production",
  "level": "error",
  "sentry_url": "https://sentry.example.com/issues/12345/"
}
```

You can route by any of these labels.

Common matcher examples:

Route only production alerts from a project:

```json
{
  "labels": {
    "project_slug": "backend-api",
    "environment": "production"
  }
}
```

Route any production Sentry alert:

```json
{
  "labels": {
    "environment": "production"
  }
}
```

Route only metric alerts:

```json
{
  "labels": {
    "sentry_resource": "metric_alert"
  }
}
```

## Deduplication and resolve behavior

Issue alerts use:

```text
sentry:issue:<issue_id>
```

Metric alerts use:

```text
sentry:metric:<sentry_alert_id>
```

This means:

- repeated Sentry issue alert triggers update the same IncidentRelay alert;
- `issue.resolved` resolves the existing IncidentRelay alert for the same issue;
- `metric_alert.resolved` resolves the existing metric alert;
- Sentry issue and metric payloads can use different resources while still resolving the correct alert.

## Security model

Sentry webhooks do not use an IncidentRelay intake token.

Instead, IncidentRelay verifies:

- route id from the URL: `/api/integrations/sentry/{route_id}`;
- route source is `sentry`;
- route and team are enabled;
- `Sentry-Hook-Signature` matches the request body and the route's Sentry Client Secret.

If the secret is missing or invalid, the webhook is rejected.

## References

- Sentry Integration Platform: https://docs.sentry.io/integrations/integration-platform/
- Sentry webhooks: https://docs.sentry.io/integrations/integration-platform/webhooks/
- Sentry issue alert webhooks: https://docs.sentry.io/integrations/integration-platform/webhooks/issue-alerts/
- Sentry alert rule action component: https://docs.sentry.io/integrations/integration-platform/ui-components/alert-rule-action/
