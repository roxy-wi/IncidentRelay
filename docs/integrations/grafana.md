# Grafana Alerting integration

IncidentRelay can receive Grafana Alerting notifications through a dedicated webhook endpoint. Each Grafana alert instance is normalized, routed, grouped, deduplicated, and processed through the standard IncidentRelay alert lifecycle.

## Endpoint

```text
POST /api/integrations/grafana
```

The endpoint requires the intake token of an active IncidentRelay route whose source is `grafana`.

```http
Authorization: Bearer <route-intake-token>
Content-Type: application/json
```

## Create an IncidentRelay route

1. Open **Routes** in IncidentRelay.
2. Create a route or edit an existing one.
3. Select **Grafana** as the source.
4. Select the team that owns the alerts.
5. Configure matchers, grouping, and the assignment target.
6. Make sure the route is active.
7. Copy the generated intake URL and route token.

A typical grouping configuration is:

```json
[
  "alertname",
  "grafana_folder",
  "instance"
]
```

Choose only labels that identify the logical incident. Avoid grouping by labels whose values change frequently.

Example route matchers:

```json
{
  "environment": "production",
  "team": "sre"
}
```

Grafana labels are available to route matchers after common labels and per-alert labels are merged.

## Configure Grafana

In Grafana:

1. Open **Alerts & IRM → Alerting → Notification configuration**.
2. Open the **Contact points** tab.
3. Add a contact point.
4. Select **Webhook** as the integration.
5. Set the URL to the IncidentRelay Grafana endpoint:

   ```text
   https://incidentrelay.example.com/api/integrations/grafana
   ```

6. Set the HTTP method to `POST`.
7. In the authorization settings, set:
   - **Authentication Header Scheme:** `Bearer`
   - **Authentication Header Credentials:** the IncidentRelay route token
8. Keep **Disable resolved message** disabled so IncidentRelay receives recovery notifications.
9. Save the contact point.
10. Use Grafana's test action to verify delivery.

Attach the contact point to the required Grafana notification policy.


### Grafana provisioning example

Grafana OSS/Enterprise can provision the contact point from a file under `provisioning/alerting`:

```yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: IncidentRelay
    receivers:
      - uid: incidentrelay-webhook
        type: webhook
        disableResolveMessage: false
        settings:
          url: https://incidentrelay.example.com/api/integrations/grafana
          httpMethod: POST
          authorization_scheme: Bearer
          authorization_credentials: $INCIDENTRELAY_ROUTE_TOKEN
```

Set `INCIDENTRELAY_ROUTE_TOKEN` in the Grafana process/container environment instead of storing the token in the provisioning file. Keep `disableResolveMessage: false` so recovery events reach IncidentRelay.

Place the file, for example, at:

```text
/etc/grafana/provisioning/alerting/incidentrelay.yaml
```

Then restart Grafana or reload the provisioned alerting resources using Grafana's provisioning API. The contact point must still be selected by an alert rule or notification policy.

## Recommended Grafana labels

Add stable labels to Grafana alert rules so IncidentRelay can route and group them predictably.

```yaml
labels:
  team: sre
  environment: production
  severity: critical
```

Useful labels include:

| Label | Purpose |
|---|---|
| `team` | Team routing |
| `environment` | Production, staging, development |
| `severity` | Alert priority |
| `service` | Affected service |
| `instance` | Affected host or instance |
| `grafana_folder` | Grafana folder |
| `alertname` | Alert rule name |

The normalizer also recognizes `oncall_team` as a fallback team label and `priority` or `level` as fallback severity labels.

## Alert normalization

IncidentRelay processes every object in Grafana's `alerts` array independently.

### Status

The alert instance status takes precedence over the top-level notification status.

Resolved-like values are normalized to:

```text
resolved
```

Other values are treated as:

```text
firing
```

This allows one Grafana notification group to contain alert instances with different states.

### Title

IncidentRelay selects the first available value from:

1. `annotations.summary`
2. `labels.alertname`
3. top-level `title`
4. `Grafana alert`

### Message

IncidentRelay selects the first available value from:

1. `annotations.description`
2. `annotations.message`
3. top-level `message`
4. `valueString`

### Severity

IncidentRelay selects the first available label from:

1. `severity`
2. `priority`
3. `level`

### Team

IncidentRelay selects the first available value from:

1. `labels.team`
2. `labels.oncall_team`
3. top-level `team`

Route matching remains authoritative. The label does not bypass normal route access or matcher checks.

## Labels added by IncidentRelay

When present in the Grafana payload, the integration exposes the following values as labels:

| IncidentRelay label | Grafana field |
|---|---|
| `dashboard_url` | `dashboardURL` |
| `panel_url` | `panelURL` |
| `generator_url` | `generatorURL` |
| `silence_url` | `silenceURL` |
| `grafana_url` | `externalURL` |
| `grafana_org_id` | `orgId` |
| `grafana_receiver` | `receiver` |
| `grafana_group_key` | `groupKey` |
| `grafana_state` | `state` |

The first available Grafana link is also stored as `event_link`. The selection order is:

1. dashboard URL
2. panel URL
3. alert rule URL
4. silence URL
5. Grafana base URL

## Deduplication

When Grafana provides `fingerprint`, IncidentRelay uses it as the deduplication key.

When `fingerprint` is missing, IncidentRelay generates a stable key from:

- Grafana source;
- alert rule UID when available;
- alert title;
- stable labels;
- Grafana organization ID.

A firing notification followed by a resolved notification with the same deduplication key updates the existing alert instead of creating another alert.

## Stored payload

IncidentRelay stores the original Grafana group context, but each normalized IncidentRelay alert keeps only its own Grafana alert instance in the stored `alerts` array.

This preserves fields such as:

- `orgId`;
- `receiver`;
- `groupKey`;
- common labels and annotations;
- dashboard and panel links;
- expression values;
- timestamps.

## Example payload

```json
{
  "receiver": "incidentrelay",
  "status": "firing",
  "orgId": 1,
  "groupKey": "{}:{alertname=\"DiskFull\"}",
  "commonLabels": {
    "team": "sre",
    "environment": "production"
  },
  "commonAnnotations": {
    "runbook_url": "https://example.com/runbooks/disk"
  },
  "externalURL": "https://grafana.example.com/",
  "title": "[FIRING:1] DiskFull",
  "state": "alerting",
  "message": "Grafana notification",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "DiskFull",
        "severity": "critical",
        "instance": "host1",
        "grafana_folder": "Infrastructure",
        "__alert_rule_uid__": "disk-full-rule"
      },
      "annotations": {
        "summary": "Disk is full",
        "description": "/var is 95% full"
      },
      "startsAt": "2026-06-21T10:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "https://grafana.example.com/alerting/grafana/disk-full-rule/view",
      "fingerprint": "grafana-disk-full-host1",
      "silenceURL": "https://grafana.example.com/alerting/silence/new",
      "dashboardURL": "https://grafana.example.com/d/system-overview",
      "panelURL": "https://grafana.example.com/d/system-overview?viewPanel=12",
      "values": {
        "A": 95
      },
      "valueString": "[ var='A' value=95 ]"
    }
  ]
}
```

## Manual test

```bash
curl -X POST \
  "https://incidentrelay.example.com/api/integrations/grafana" \
  -H "Authorization: Bearer ROUTE_INTAKE_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @grafana-payload.json
```

A successful response contains one result for every object in the Grafana `alerts` array.

```json
[
  {
    "created": true,
    "alert_id": 123,
    "group_id": 45,
    "status": "firing",
    "team_id": 2,
    "team_slug": "sre",
    "route_id": 7,
    "routing_error": null,
    "trace_id": "..."
  }
]
```

## HTTP responses

| Status | Meaning |
|---|---|
| `200` | All alert instances were processed successfully |
| `202` | Processing was accepted but not fully completed synchronously |
| `207` | The notification contains mixed processing outcomes |
| `400` | Invalid payload or routing failure |
| `401` | Route intake token is missing or invalid |

When routing fails, the response includes a `trace_id`. An administrator can use the alert explain trace to inspect matcher evaluation and the exact routing failure.

## Troubleshooting

### Route intake token is required

Grafana did not send an authorization header.

Verify:

```text
Authentication Header Scheme: Bearer
Authentication Header Credentials: <route-intake-token>
```

Do not add the word `Bearer` to the credentials field when the scheme is configured separately.

### Alert did not match any active route

Check that:

- the route is active;
- the route source is `grafana`;
- the token belongs to that route;
- the incoming labels satisfy every configured matcher;
- the route's team is active and accessible.

Use the returned `trace_id` to inspect route evaluation.

### Resolved alerts are not received

Make sure **Disable resolved message** is not enabled in the Grafana webhook contact point.

IncidentRelay uses the status of each item in the `alerts` array, not only the top-level status.

### Alerts are duplicated

Check that Grafana sends a stable `fingerprint`. When the fingerprint is unavailable, keep rule UID and routing labels stable between firing and resolved notifications.

Do not include volatile values in labels used to identify an alert instance.

### Dashboard or panel links are empty

Grafana includes dashboard and panel links only when the alert rule is associated with the relevant dashboard and panel metadata. The alert rule URL remains available through `generatorURL`.

### Test notification does not match production routing

Grafana test payload labels can differ from real alert-rule labels. Compare the received labels in the explain trace with the route matchers.

## Security

- Use HTTPS for the webhook endpoint.
- Store route intake tokens as secrets.
- Use a separate route token for each integration or trust boundary.
- Rotate a token immediately if it is exposed.
- Do not place the token in the URL.
- Restrict route matchers so a leaked token cannot route unrelated alerts.
