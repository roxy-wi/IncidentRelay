# On-call Health

On-call Health helps operators verify that rotations and teams are ready to receive and process alerts before an incident occurs.

The health indicator is shown directly in the **Rotations** and **Teams** tables. It provides a fast summary in the table row and opens a detailed diagnostics modal when selected.

## Health indicators

Each row displays one of the following indicators:

- **Green check** — no critical or warning issues were found.
- **Yellow exclamation mark** — one or more warnings were found and there are no critical issues.
- **Red cross** — one or more critical issues were found.
- **Question mark** — the health summary is still loading, could not be calculated, or was not returned.

Hover over the indicator to see a short summary. Select the indicator to open the full diagnostics modal.

Informational notes do not change a row from green to yellow or red.

## Rotation health

Rotation health checks whether a rotation can produce a usable on-call assignment.

The lightweight table summary checks structural problems such as:

- the rotation is disabled;
- the rotation has no layers;
- the rotation has no enabled layers;
- an enabled layer has no members;
- the rotation has no active members;
- only one active member is available;
- inactive users are still assigned to enabled layers.

The full diagnostics modal can additionally check:

- the current on-call assignment;
- future schedule gaps in the checked window;
- inactive or deleted assignees;
- notification delivery readiness;
- related routing and assignment problems.

The table summary is intentionally lightweight. Full schedule and delivery checks are calculated only when the diagnostics modal is opened.

## Team health

Team health checks whether alerts routed to a team can resolve to a valid assignment and delivery path.

Checks can include:

- the team has no enabled rotation;
- an enabled route has neither a rotation nor an escalation policy;
- a related rotation has critical issues or warnings;
- enabled routes do not have usable notification channels;
- route or escalation configuration cannot resolve an assignment target.

A route does not need a direct rotation when it has an escalation policy. The policy may resolve the target through a rotation or a user rule.

## Diagnostics modal

The diagnostics modal shows:

- the effective health status;
- critical issue count;
- warning count;
- informational count;
- the checked time window;
- detailed issue cards grouped by severity;
- suggested actions when a hint is available.

Each issue has a stable machine-readable `code`. This allows API clients and tests to identify a condition without depending on display text.

Examples of issue codes include:

```text
rotation_has_no_layers
rotation_has_no_enabled_layers
enabled_layer_has_no_members
rotation_has_no_active_members
rotation_has_single_active_member
layer_has_inactive_members
schedule_gap
route_has_no_assignment_target
```

The exact set of issue codes may grow as additional diagnostics are added.

## Filtering and table refreshes

Health indicators are refreshed after the Rotations or Teams table is rendered again.

This includes:

- filtering rotations by team;
- changing search or status filters;
- reloading the table after an edit;
- switching between visible groups where supported.

Previously loaded summaries may be reused from the browser-side cache. Newly visible rows are requested from the summary API.

## Performance model

On-call Health uses two levels of diagnostics.

### Lightweight summaries

Summary endpoints are used for table indicators. They perform structural checks and avoid full schedule scans.

```text
GET /api/oncall-health/rotations/summaries
GET /api/oncall-health/teams/summaries
```

IDs are supplied as repeated query parameters:

```text
/api/oncall-health/rotations/summaries?rotation_id=3&rotation_id=4
/api/oncall-health/teams/summaries?team_id=1&team_id=2
```

The response contains both an ordered `items` list and a `by_id` object for fast lookup:

```json
{
  "items": [
    {
      "rotation_id": 3,
      "summary": {
        "status": "warning",
        "critical": 0,
        "warning": 1,
        "info": 0,
        "total": 1,
        "partial": true
      }
    }
  ],
  "by_id": {
    "3": {
      "status": "warning",
      "critical": 0,
      "warning": 1,
      "info": 0,
      "total": 1,
      "partial": true
    }
  }
}
```

Missing or inaccessible objects are omitted from the response.

### Full diagnostics

Detail endpoints are called only when the user opens the health modal:

```text
GET /api/oncall-health/rotations/{rotation_id}
GET /api/oncall-health/teams/{team_id}
```

A full response includes the summary, checked window and detailed issues:

```json
{
  "scope": "rotation",
  "rotation_id": 3,
  "rotation_name": "Primary on-call",
  "team_id": 1,
  "window": {
    "starts_at": "2026-06-20T00:00:00Z",
    "ends_at": "2026-06-27T00:00:00Z"
  },
  "summary": {
    "status": "critical",
    "critical": 1,
    "warning": 0,
    "info": 0,
    "total": 1
  },
  "issues": [
    {
      "severity": "critical",
      "code": "schedule_gap",
      "title": "Schedule gap detected",
      "message": "No active on-call user can be resolved for part of the checked window.",
      "target_type": "rotation",
      "target_id": 3,
      "starts_at": "2026-06-21T02:00:00Z",
      "ends_at": "2026-06-21T08:00:00Z"
    }
  ]
}
```

## Permissions

On-call Health follows the same read permissions as the related rotation or team.

- Users who can read a rotation can request its health summary and details.
- Users who can read a team can request its health summary and details.
- Inaccessible objects are omitted from batch summary responses.
- Detail endpoints return an access error when the object exists but the current user cannot read it.

Health access does not grant permission to edit teams, rotations, layers, routes or escalation policies.

## Troubleshooting

### The indicator remains a question mark

Check the browser network panel for a request to one of the summary endpoints.

If no request is sent:

1. Verify that `oncall_health.js` is included on the page.
2. Verify that the table render function calls the health summary loader after rebuilding rows.
3. Check the browser console for JavaScript errors.

If the request returns `404`:

1. Verify that `oncall_health_bp` is registered with the `/api/oncall-health` prefix.
2. Verify that the exact summaries route exists in `oncall_health_view.py`.
3. Restart the application after changing blueprint registration.

If the request succeeds but the indicator stays unchanged, verify that the row has the expected `data-rotation-health-id` or `data-team-health-id` attribute.

### Health stops updating after filtering

The table is rebuilt when a filter changes. The render function must call the appropriate loader after inserting the new rows:

```javascript
window.loadRotationHealthSummariesForVisibleRows();
```

or:

```javascript
window.loadTeamHealthSummariesForVisibleRows();
```

The client-side summary cache should store the full summary by object ID, not only a set of IDs that were previously loaded.

### The modal opens empty on page load

The shared health modal must be hidden initially:

```html
<div class="app-modal" id="rotation-health-modal" style="display: none;" aria-hidden="true">
```

Do not call the modal open function during page initialization. Open it only after a user selects a health indicator.

### Summary requests are slow

Verify that row summaries do not call full diagnostics.

Summary code should not perform:

- future schedule scans;
- repeated `get_current_oncall_user()` calls;
- notification delivery checks;
- full route or escalation resolution;
- per-row lazy database queries.

Rotation summaries should preload layers, members and users in batches where possible. Full checks belong only in the detail endpoint.

## API documentation

The On-call Health endpoints are also included in the generated OpenAPI specification.

Swagger UI:

```text
/docs
```

OpenAPI JSON:

```text
/api/openapi.json
```
