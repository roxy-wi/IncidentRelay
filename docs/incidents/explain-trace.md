# Alert Explain Trace

Alert Explain Trace records how IncidentRelay processed an incoming alert.

It is useful when you need to understand why an alert was routed to a specific team, grouped into an existing incident, suppressed by maintenance or silence, or rejected because no route matched.

## When traces are created

IncidentRelay creates an explain trace for each incoming alert processed by `upsert_alert()`.

A trace is created for both successful and stopped processing paths:

- alert group created
- alert group reused
- alert updated
- alert resolved
- routing failed
- incident suppressed
- orphan resolved alert ignored
- maintenance matched
- notification scheduled or suppressed

## Ingest API response

Integration endpoints include `trace_id` in each processed alert response.

Example successful response:

```json
[
  {
    "created": true,
    "id": 123,
    "group_id": 123,
    "alert_id": 456,
    "status": "firing",
    "outcome": "created",
    "processing_status": "completed",
    "reason": null,
    "trace_id": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
    "routing_error": null,
    "team_id": 1,
    "team_slug": "infra",
    "route_id": 10,
    "rotation_id": null,
    "assignee": null
  }
]
```

Example routing failure response:

```json
[
  {
    "created": false,
    "id": null,
    "group_id": null,
    "alert_id": null,
    "status": "firing",
    "outcome": "routing_failed",
    "processing_status": "stopped",
    "reason": "Alert did not match any active route.",
    "trace_id": "a1e26edb-5989-4a17-bf70-cf73154c2412",
    "routing_error": "Alert did not match any active route.",
    "team_id": null,
    "team_slug": null,
    "route_id": null,
    "rotation_id": null,
    "assignee": null
  }
]
```

If all alerts in a request fail routing, the API returns HTTP `400`.

If a batch contains both successful and failed items, the API returns HTTP `207`.

## API endpoints

### List traces for an alert group

```http
GET /api/alerts/{alert_group_id}/explain
```

Returns explain traces linked to an existing alert group.

Example response:

```json
[
  {
    "id": 12,
    "trace_id": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
    "mode": "live",
    "group_id": 123,
    "alert_id": 456,
    "source": "alertmanager",
    "dedup_key": "disk-full-host1",
    "status": "completed",
    "outcome": "created",
    "reason": null,
    "input_summary": {},
    "result": {},
    "started_at": "2026-06-19T17:00:00",
    "finished_at": "2026-06-19T17:00:01",
    "steps": []
  }
]
```

### Get one trace with steps

```http
GET /api/alerts/explain/{trace_id}
```

Returns a single trace with ordered processing steps.

Example response:

```json
{
  "id": 12,
  "trace_id": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
  "mode": "live",
  "group_id": 123,
  "alert_id": 456,
  "source": "alertmanager",
  "dedup_key": "disk-full-host1",
  "status": "completed",
  "outcome": "created",
  "reason": null,
  "input_summary": {},
  "result": {},
  "started_at": "2026-06-19T17:00:00",
  "finished_at": "2026-06-19T17:00:01",
  "steps": [
    {
      "id": 100,
      "position": 1,
      "stage": "intake",
      "code": "alert_received",
      "status": "success",
      "title": "Alert received",
      "message": null,
      "data": {},
      "created_at": "2026-06-19T17:00:00"
    }
  ]
}
```

## UI

Existing alert groups show explain data in the alert details modal.

Open:

```text
Alerts -> alert row -> Details -> Explain
```

For traces that are not linked to an alert group, for example routing failures, use:

```text
Alerts -> Explain trace
```

Paste the `trace_id` from the ingest API response.

You can also open a trace directly with a deep link:

```text
/alerts?trace_id=<trace_id>
```

or:

```text
/alerts?explain_trace_id=<trace_id>
```

After the trace opens, the query parameter is removed from the browser URL.

## Access control

Traces linked to an alert group use the same read access checks as the alert group.

Orphan traces are traces without `group_id`. They can be read only by administrators.

## Retention

Explain traces are cleaned up automatically by the scheduler.

Default retention:

```ini
[alerts]
alert_explain_trace_retention_days = 30
```

Default cleanup interval:

```ini
[scheduler]
alert_explain_trace_cleanup_interval_seconds = 86400
```

Set `alert_explain_trace_retention_days` to a positive integer.

## Troubleshooting

### Ingest returns routing_failed

Open the returned `trace_id` and check for:

- `alert_received`
- `route_not_matched`

This usually means the alert source, team, route matchers, labels or route state do not match the incoming payload.

### Trace exists but has no alert group

This is expected for stopped processing paths, for example:

- routing failed
- incident suppressed
- resolved alert received without an existing firing group

### Alert details Explain tab is empty

Check that the alert group has at least one linked trace:

```http
GET /api/alerts/{alert_group_id}/explain
```

If this returns an empty list, the alert group was probably created before Explain Trace was enabled.
