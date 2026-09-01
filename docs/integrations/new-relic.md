---
title: New Relic
description: Send New Relic Alerts Workflow issue notifications to IncidentRelay through a native webhook route.
---

# New Relic integration

IncidentRelay accepts New Relic issue notifications from **Alerts → Workflows** through a native incoming route.

Endpoint:

```text
POST /api/integrations/new-relic
```

## Create the IncidentRelay route

Create a route with:

```text
Source: New Relic
```

The default grouping field for a new New Relic route is:

```json
["new_relic_issue_id"]
```

Attach the required notification channels, save the route, and copy its intake token.

## Configure the New Relic webhook destination

In New Relic, open **Alerts → Destinations**, create a **Webhook** destination, and use:

```text
https://incidentrelay.example.com/api/integrations/new-relic
```

Enable **Bearer Token** authorization and use the IncidentRelay route intake token as the token value.

Then create or edit an **Alerts Workflow**, select the webhook destination, and use the following JSON message template:

```handlebars
{
  "issue_id": {{json issueId}},
  "title": {{json issueTitle}},
  "state": {{json state}},
  "status": {{json status}},
  "priority": {{json priority}},
  "issue_url": {{json issuePageUrl}},
  "condition_name": {{#if accumulations.conditionName}}{{json accumulations.conditionName.[0]}}{{else}}null{{/if}},
  "policy_name": {{#if accumulations.policyName}}{{json accumulations.policyName.[0]}}{{else}}null{{/if}},
  "entity_guid": {{#if entitiesData.entities.[0].id}}{{json entitiesData.entities.[0].id}}{{else}}null{{/if}},
  "entity_name": {{#if entitiesData.entities.[0].name}}{{json entitiesData.entities.[0].name}}{{else}}null{{/if}},
  "entity_type": {{#if entitiesData.types.[0]}}{{json entitiesData.types.[0]}}{{else}}null{{/if}},
  "labels": {{#if accumulations.rawTag}}{{json accumulations.rawTag}}{{else}}{}{{/if}}
}
```

Use **Send test notification** in New Relic before activating the workflow.

## Lifecycle and deduplication

`issueId` is the preferred identity. The recommended template maps it to `issue_id`, and IncidentRelay uses it as both the external id and deduplication key.

This means notifications for the same New Relic issue update one IncidentRelay alert instead of creating a new alert for every workflow update.

Resolved-like values are mapped to `resolved`:

```text
closed
resolved
recovered
inactive
```

Other issue states remain `firing`. A non-empty `issueClosedAt` field in a native/custom payload is also treated as resolved.

## Severity mapping

IncidentRelay maps New Relic issue priority/severity directly through the common severity normalizer:

| New Relic | IncidentRelay |
|---|---|
| `CRITICAL` | `critical` |
| `HIGH` | `high` |
| `MEDIUM` | `medium` |
| `WARNING` | `warning` |
| `LOW` | `low` |

If neither priority nor severity is present, the event uses `info`.

## Labels

The recommended template sends `accumulations.rawTag` as `labels`. New Relic tag values can be arrays; IncidentRelay flattens each label to its first non-empty value so it can be used by matchers.

IncidentRelay also adds normalized metadata labels:

```text
new_relic_issue_id
new_relic_condition
new_relic_policy
new_relic_entity_guid
new_relic_entity_name
new_relic_entity_type
new_relic_priority
new_relic_state
new_relic_status
event_link
```

A `team` or `oncall_team` label can select a team through the normal routing behavior.

## Native Workflow payload compatibility

The normalizer also accepts common native New Relic fields directly, including:

```text
issueId
issueTitle
issuePageUrl
priority
state
status
accumulations.conditionName
accumulations.policyName
accumulations.rawTag
entitiesData.entities
entitiesData.types
```

A custom template is still recommended because it makes the integration contract explicit and easier to troubleshoot.

## Test request

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/new-relic' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "issue_id": "issue-example-1",
    "title": "API latency is high",
    "state": "ACTIVATED",
    "status": "CREATED",
    "priority": "CRITICAL",
    "issue_url": "https://one.newrelic.com/redirects/issue/issue-example-1",
    "condition_name": "API latency",
    "policy_name": "Production API",
    "entity_name": "checkout-api",
    "labels": {
      "environment": "production",
      "service": "checkout",
      "team": "sre"
    }
  }'
```

Send the same `issue_id` with:

```json
{
  "state": "CLOSED",
  "status": "CLOSED"
}
```

to resolve the existing alert.

## Troubleshooting

- `401 Route intake token is required`: verify the Bearer Token configured on the New Relic webhook destination.
- `400 Route source must be new_relic`: the token belongs to a route with another source.
- Open and close create separate alerts: make sure every workflow notification sends the same `issueId` as `issue_id`.
- Route/service matching does not work: inspect normalized labels in Alert details and compare them with the matcher.
- The webhook template cannot be saved: use New Relic's preview and make sure the rendered template is valid JSON.
