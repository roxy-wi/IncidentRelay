# RMON integration

IncidentRelay can receive alerts from RMON through a dedicated inbound integration. RMON sends each alert to IncidentRelay with a route intake token, and IncidentRelay processes it through the standard routing, grouping, suppression, notification, escalation, and explain-trace pipeline.

## Endpoint

```text
POST /api/integrations/rmon
```

The endpoint requires the intake token of an active IncidentRelay route whose source is `rmon`.

```http
Authorization: Bearer <route-intake-token>
Content-Type: application/json
```

## Create an IncidentRelay route

1. Open **Routes** in IncidentRelay.
2. Create a route or edit an existing one.
3. Select **RMON** as the source.
4. Select the team that owns the alerts.
5. Configure route matchers.
6. Configure grouping.
7. Select a rotation or escalation policy.
8. Make sure the route is active.
9. Copy the route intake token.

Recommended grouping:

```json
[
  "rmon_check_id",
  "rmon_check_type"
]
```

Example matchers:

```json
{
  "environment": "production",
  "rmon_region": "eu-west"
}
```

Only use stable labels for grouping. Do not group by values that change between repeated executions of the same check.

## Configure RMON

In the RMON IncidentRelay channel, set:

```text
Channel name: https://incidentrelay.example.com
Token: <route-intake-token>
```

The channel URL must contain only the base IncidentRelay URL. RMON appends the integration path automatically:

```text
/api/integrations/rmon
```

Do not place the token in the URL.

## Alert lifecycle

RMON sends:

```text
firing
```

for active failures and:

```text
resolved
```

for recovery events.

IncidentRelay updates the existing alert when the firing and resolved notifications use the same fingerprint.

Resolved-like values such as the following are also normalized to `resolved`:

```text
clear
cleared
closed
info
normal
ok
recover
recovered
resolved
up
```

Other values are treated as `firing`.

## Payload fields

### Required field

| Field | Description |
|---|---|
| `title` | Human-readable alert title |

### Alert identity

| Field | Description |
|---|---|
| `fingerprint` | Stable key used for deduplication |
| `external_id` | External check or event identifier |
| `check_id` | RMON check identifier |
| `multi_check_id` | RMON multi-check identifier |
| `state_id` | RMON check-state identifier |

### Check context

| Field | Description |
|---|---|
| `rmon_name` | Name of the RMON instance |
| `check_name` | Human-readable check name |
| `check_type` | Check type, such as `http` |
| `target` | Checked host, URL, or other target |
| `agent` | Agent that executed the check |
| `region` | Check region |
| `country` | Check country |
| `description` | Check description |

### Routing and grouping

| Field | Description |
|---|---|
| `team` | Optional IncidentRelay team slug fallback |
| `severity` | Alert severity |
| `status` | Alert lifecycle status |
| `labels` | Additional routing and grouping labels |

### Runbook and links

| Field | Description |
|---|---|
| `runbook` | Runbook text or URL |
| `runbook_url` | Runbook URL |
| `event_link` | Direct source event or check URL |

Additional fields are accepted and retained in the stored payload.

## Normalized labels

IncidentRelay adds the following labels when corresponding values are available:

| IncidentRelay label | Source field |
|---|---|
| `alertname` | `check_name` or `title` |
| `severity` | `severity` |
| `rmon_name` | `rmon_name` |
| `rmon_check_id` | `multi_check_id`, `check_id`, or existing label |
| `rmon_state_id` | `state_id` |
| `rmon_check_name` | `check_name` |
| `rmon_check_type` | `check_type` |
| `target` | `target` or `instance` |
| `rmon_agent` | `agent` |
| `rmon_region` | `region` |
| `rmon_country` | `country` |
| `runbook_url` | `runbook_url` |
| `event_link` | First available event or runbook link |

Existing labels supplied by RMON are preserved.

## Team selection

IncidentRelay selects the optional team hint from the first available value:

1. top-level `team`;
2. `labels.team`;
3. `labels.oncall_team`.

The route remains authoritative. A team hint does not bypass route token, source, matcher, or access checks.

## Severity

IncidentRelay selects severity from:

1. top-level `severity`;
2. `labels.severity`;
3. `warning`.

## Deduplication

When `fingerprint` is present and valid, IncidentRelay uses it as the deduplication key.

Values such as the following are ignored:

```text
None
null
None None
null null
```

When a valid fingerprint is unavailable, IncidentRelay generates a stable key from:

- source `rmon`;
- external or check identifier;
- title;
- normalized labels.

RMON should keep the same fingerprint between the firing and recovery notifications for one logical check failure.

## Example payload

```json
{
  "title": "[rmon-production] critical: HTTP check failed",
  "message": "critical: HTTP check failed",
  "severity": "critical",
  "status": "firing",
  "fingerprint": "42 7",
  "external_id": 42,
  "rmon_name": "rmon-production",
  "multi_check_id": 42,
  "state_id": 7,
  "check_name": "Public API",
  "check_type": "http",
  "target": "https://api.example.com/health",
  "agent": "eu-west-agent",
  "region": "eu-west",
  "country": "DE",
  "runbook_url": "https://example.com/runbooks/public-api",
  "labels": {
    "team": "sre",
    "environment": "production"
  }
}
```

## Manual test

Save the example payload as `rmon-payload.json` and run:

```bash
curl -X POST   "https://incidentrelay.example.com/api/integrations/rmon"   -H "Authorization: Bearer ROUTE_INTAKE_TOKEN"   -H "Content-Type: application/json"   --data-binary @rmon-payload.json
```

A successful response contains one ingest result:

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
| `200` | Alert processed successfully |
| `202` | Processing accepted but not fully completed synchronously |
| `207` | Mixed processing outcome |
| `400` | Invalid payload or routing failure |
| `401` | Route intake token is missing or invalid |

A routing failure response includes a `trace_id`. Administrators can inspect the explain trace to see route matcher evaluation and the exact failure reason.

## Troubleshooting

### Route intake token is required

RMON did not send the bearer token, or the channel token is empty.

Check the RMON channel configuration:

```text
Token: <route-intake-token>
```

### Alert did not match any active route

Verify that:

- the route is active;
- the route source is `rmon`;
- the token belongs to that route;
- every configured matcher matches the received labels;
- the team is active;
- the route has a rotation or escalation policy.

Use the returned `trace_id` to inspect routing.

### Recovery creates another alert

Make sure the same `fingerprint` is sent for both firing and resolved notifications.

The fingerprint must identify the logical check failure and must not contain changing timestamps or random values.

### Alerts from different checks are merged

Use a fingerprint containing the check identifier and state identifier, or another stable combination unique to the logical check event.

Recommended example:

```text
<multi_check_id> <state_id>
```

### Runbook link is missing

Set `runbook_url` to an absolute `http://` or `https://` URL. A non-URL runbook value remains available in the stored payload but is not used as a clickable event link.

### Test notification behaves differently

Test notifications may not contain `state_id`, check metadata, or production labels. IncidentRelay generates a fallback deduplication key when the test payload has no valid fingerprint.

Compare the labels shown in the explain trace with the route matchers.

## Security

- Use HTTPS.
- Keep the route intake token secret.
- Use a separate route token for each RMON instance or trust boundary.
- Rotate exposed tokens immediately.
- Do not send the token inside the JSON payload.
- Do not put the token in the URL.
- Restrict route matchers to the expected RMON labels.
