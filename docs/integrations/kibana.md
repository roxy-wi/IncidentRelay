---
title: Kibana Alerting
description: Receive per-alert Elastic Kibana Webhook connector notifications in IncidentRelay.
---

# Kibana Alerting integration

Receive **Elastic Kibana** rule actions through a Webhook connector. This
integration creates/updates technical AlertGroups; it does not create Change
Events or automatically declare operational Incidents.

Endpoint: `POST /api/integrations/kibana`

## IncidentRelay route

Create a Route with **Source = Kibana Alerting** and copy its intake token.
Attach the required team, escalation/rotation, channels and service settings.
The suggested grouping is:

```json
["kibana_rule_id", "kibana_alert_id"]
```

## Kibana Webhook connector

1. In **Stack Management → Connectors**, create a **Webhook** connector using
   method `POST` and URL:

   `https://incidentrelay.example.com/api/integrations/kibana`

2. Add custom HTTP headers:

   ```text
   Content-Type: application/json
   Authorization: Bearer <incidentrelay-route-intake-token>
   ```

3. Create or edit an alerting rule. Use **For each alert**, not an aggregate
   summary action. Choose the Webhook connector for the active action and enter:

   ```json
   {
     "rule_id": "{{rule.id}}",
     "alert_id": "{{alert.id}}",
     "space_id": "{{rule.spaceId}}",
     "rule_name": "{{rule.name}}",
     "message": "{{context.reason}}",
     "rule_url": "{{rule.url}}",
     "status": "active"
   }
   ```

   `context.reason` may be unavailable for some rule types; you can remove it
   or replace it with a rule-specific variable. Kibana escapes Mustache values
   in Webhook connector JSON bodies by default. Avoid triple-brace insertion
   for untrusted text.

4. **Configure a separate recovery action** for the rule, when supported by
   its rule type. Send the **same** `rule_id`, `alert_id` and `space_id` with:

   ```json
   "status": "recovered"
   ```

   If your Kibana action group is configured to send recovery data, you can
   instead pass `"action_group": "{{alert.actionGroup}}"`; the normalizer
   maps `recovered` to `resolved`. A recovery notification must carry the same
   alert identity as the original active notification.

5. Test both triggering and recovery. In the AlertGroup, confirm that the
   original child Alert is resolved, not replaced by a new ID.

Kibana action group names and available variables vary by rule type. Consult
[Kibana rule action variables](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-action-variables)
and the [Webhook connector guide](https://www.elastic.co/docs/reference/kibana/connectors-kibana/webhook-action-type).

## Identity and delivery

The stable dedup key is based on `space_id + rule_id + alert_id` plus the
IncidentRelay intake Route. The message, title, severity and flapping flag
never change that identity. `space_id` defaults to `default` when omitted.

Kibana's per-alert action frequency can send repeated `active` notifications;
IncidentRelay updates the same child Alert. Explicit `recovered`, `resolved`,
`closed` or `ok` notifications resolve the existing Alert. Missing notifications
are **not** interpreted as recovery.

Only per-alert messages containing both `rule_id` and `alert_id` are accepted.
Summaries without stable individual IDs return a validation error rather than
creating noisy, incorrectly grouped alerts.

## Useful optional fields

| Field | Description |
| --- | --- |
| `severity` | critical/high/medium/warning/low/info |
| `title`, `rule_name`, `message`, `reason` | Display context |
| `labels`, `team` | For service matching and Event Orchestration |
| `rule_url`, `event_link` | Absolute HTTP(S) rule/alert URL |
| `flapping` | Kibana flapping metadata (observational; does not resolve AlertGroup) |
| `action_group` | Can distinguish `recovered` from active actions |

Both integrations reuse existing Route tokens, RBAC, alert lifecycle, escalation,
notification channels, Alert Explain and the Event Orchestration simulator.
No additional secrets or database migration are needed.
