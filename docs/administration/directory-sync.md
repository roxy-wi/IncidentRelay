---
title: Directory synchronization
description: Connect an external API, map teams and people, and review your first on-call import.
---

# Directory synchronization

Directory synchronization imports teams, people and on-call schedules into IncidentRelay. IR reads the external API at the interval you choose. It does not send local changes back to that system.

A **source** is one connection: its API address, credentials, requests, field mapping and update rules. Each source belongs to one destination group in IR.

## Before you start

| Requirement | Purpose |
|---|---|
| An administrator account | Global administrators can choose any active group. Group user administrators can configure sources only in groups they administer. |
| The external API address | For example, `https://org-service.example.com`, where the teams and schedules live. |
| External API credentials | For org-service, a PAT that can read teams, employees, schedules and current duty. |
| A running IR scheduler | It processes previews, applies imports and runs periodic updates. |
| Network access from IR | Both web and scheduler processes must resolve the API hostname, reach its port and trust its TLS certificate. |

When upgrading, run `python manage.py migrate` before starting the updated web and scheduler processes. See [Scheduler](scheduler.md) and [Installation](../getting-started/installation.md).

**The two connections use different tokens.** The source's authentication headers contain the **external system's** token. An **IR personal token** is needed only when a script configures IR through its API. Configuration through the interface uses your existing IR login session.

## First import through the interface

### 1. Open the source form

Go to **Administration → Directory synchronization → Add source**. Configuration opens in a modal. **Configure** on an existing source opens the same modal for editing.

The form already contains requests and mapping for org-service. Keep these defaults when connecting that system and enter your own connection details. For another API, use the request and mapping guides below.

### 2. Enter connection details

| Field | What to enter |
|---|---|
| Name | A recognizable name, such as `Platform on-call`. |
| Destination group | The IR group where teams should appear. This cannot change after creating the source. |
| API base URL | For example, `https://org-service.example.com`. The operations already contain the `/api/v1/...` paths. |
| Network access | Use public networks for a public API. For an internal API, configure the server allowlist and select the server-allowed networks option. |
| Skip TLS certificate verification | Off by default. Enable to connect to an API with a self-signed certificate without configuring CA trust. Disables certificate and hostname verification for this source only. |
| Authentication headers | JSON headers expected by the external system. |

For org-service:

```json
{
  "Authorization": "PAT replace-with-your-PAT"
}
```

For a Bearer-based API, the value would be `Bearer your-token`. Use the external API's actual authentication scheme.

Headers are encrypted. The field becomes blank after saving because the server never returns the secret to the browser. On later edits, leaving it blank **preserves existing headers**, a new JSON object replaces them, and `{}` clears them. Keep tokens out of URLs and mapping fields.

### 3. Save the initial settings

For the first import, the defaults are a useful starting point:

- Full synchronization: **3600 seconds**, once an hour.
- Current-duty refresh: **60 seconds**.
- Calendar horizon: **2 months**, the current and next month.
- Local edits, managing matched existing teams and deleting missing objects: off.
- Membership authority: **Synchronization API**.

Click **Save configuration** in the modal footer. The modal remains open. Saving creates the connection settings; teams and people are created when you apply a preview.

### 4. Inspect the response

Click **Inspect response fields**. IR requests the first catalog page and displays field names and types, for example:

```json
{
  "teams": [{"enrolledScopeUuid": "str", "name": "str"}],
  "nextPageToken": "str"
}
```

`str` means a string, not a real team name or ID. This checks the catalog connection and helps you select mapping paths. The other requests are exercised by the preview. After changing operations or mapping, save before checking again.

### 5. Preview and match teams

Click **Preview changes**. The scheduler runs the job and the modal updates when it finishes. You can close it while waiting: the job continues. Click **Configure** again to retrieve its current state.

| Action | What applying the preview will do |
|---|---|
| `create` | Create a user, team, membership, rotation or shift. |
| `update` | Change the listed object fields. |
| `skip` | Leave a matched team unchanged because managing existing teams is off. |
| `delete` | Remove a missing managed object or deactivate its membership. |

A preview stores the plan without changing teams, people or schedules. Review membership, planned changes and especially `delete` rows.

Once the catalog has loaded, the mapping section offers selectors for matching external teams to existing teams in the destination group. Without an explicit match, IR looks for one exact name match; if there is none, it creates a team. Multiple matching names require an explicit choice. Also enable **Manage matched existing teams** if the source should update that team.

After changing matches, save and request a new preview. Once applied, an external team's stored identity cannot be rebound to a different local team.

### 6. Apply and enable updates

Click **Apply preview** within **15 minutes**. If it has expired, or local data has changed enough to alter the plan, request another preview.

After a successful application:

1. Check the imported teams and rotations in IR.
2. Enable **Periodic synchronization enabled** in the source settings.
3. Click **Save configuration**.

**Run now** performs the next full import without waiting for its interval. The source list shows status, any error and the last successful import time.

## Choosing update behavior

| Setting | Off | On |
|---|---|---|
| Allow local edits | Imported resources are protected against manual edits. | Local edits are allowed. The next import replaces matching imported fields. |
| Manage matched existing teams | Pre-existing teams are skipped. | The source can update matched teams. A team owned by another source cannot be adopted. |
| Remove missing managed objects | Objects that stop appearing are retained. | A complete successful import removes only objects managed by this source. |
| Periodic synchronization enabled | Automatic refreshes are paused. | Full imports and current-duty refreshes run on schedule. |

Teams **created by the source** continue to update regardless of the setting for matched existing teams. Shared and pre-existing user profiles are not overwritten.

Team and rotation removal uses IR soft deletion. Shift removal is limited to the successfully fetched window. When a person leaves, owned memberships are deactivated; the global account and OIDC identity remain. A failed request does not delete previous data.

| Interval | What it refreshes | Values |
|---|---|---|
| Full synchronization | Teams, profiles, memberships and calendar shifts | `3600` means hourly; `600` means every ten minutes. Range: 60–604800 seconds. |
| Current duty | Actual assignments from the `current` operation | `60` means every minute. Range: 10–3600 seconds. |
| Calendar horizon | Calendar months, including the current month | `2` in November includes November and December. Range: 1–11 months. |

Window boundaries use UTC. For example, on November 10, 2026, a horizon of `2` requests `2026-11-01T00:00:00Z` through `2027-01-01T00:00:00Z`.

**To change an active source**, uncheck periodic synchronization, edit and save. Configuration or credential changes require a new preview and application before periodic updates can be enabled again.

## Users, roles and OIDC

Every referenced person needs a stable external ID and a valid email. On first import, IR matches email case-insensitively. One matching account is reused; no match creates an account **without a local password or global administrator privileges**. Subsequent imports use the stored external identity.

To let imported people sign in through OIDC:

1. Configure and enable the OIDC provider in IR.
2. Enable email linking (`auto_link_by_email`).
3. Ensure the directory email matches the email supplied by OIDC at login.
4. The person's OIDC login links to the existing account. `auto_create_users` is not required for that account.

Provider domain and verified-email policies continue to apply. Missing emails, duplicates or a matching deleted account stop the import: resolve the conflict first.

**Membership authority** chooses who assigns access:

- **Synchronization API (`sync`)** creates memberships from the external roster and protects its owned roles from OIDC synchronization. Default roles are group `viewer`, team member `responder` and responsible person `manager`.
- **OIDC (`oidc`)** leaves memberships and roles to configured SSO mappings. The source still imports accounts, teams and schedules. Configure the SSO mappings before people sign in.

Either option permits OIDC login. Set source roles through `group_role`, `member_role` and `responsible_role` in mapping JSON. Personal notification and interface preferences remain personal.

In org-service, `roster` means on-call participants, not necessarily every employee in a department. In `sync` mode, the responsible person also becomes a team member. Shift and replacement participants outside that roster receive accounts, but participation alone does not make them team members. The source also creates group access for them if absent.

## Adapting another API: operations

**API operations (JSON)** describe where to request data. **Field mapping and membership roles (JSON)** describe how to read the response, such as which field contains an email.

| Operation | Purpose | Response after selecting `items` |
|---|---|---|
| `teams` | Required team catalog. | Array of teams. |
| `team` | Optional details when the catalog does not include membership and schedules. | Team object. |
| `user` | Optional profile lookup when the roster does not include profile/email data. | Object or one-element array; a catalog with `user_fetch: all`. |
| `shifts` | Required shifts for one team and time window. | Array, including `[]` when there are no shifts. |
| `current` | Optional actual duty lookup. | Array of slot results in batch mode. |

These org-service operations can be pasted as the entire operations field:

```json
{
  "teams": {
    "method": "GET", "path": "/api/v1/support-team-catalog", "items": "teams",
    "pagination": {"mode": "cursor", "parameter": "pageToken", "next_path": "nextPageToken", "size_parameter": "pageSize", "size": 100}
  },
  "team": {"method": "GET", "path": "/api/v1/duty-scopes/{team_id}"},
  "user": {"method": "GET", "path": "/api/v1/employees", "params": {"uuid": "{user_id}"}, "items": "employees"},
  "shifts": {
    "method": "GET", "path": "/api/v1/duty-scopes/{team_id}/shifts",
    "params": {"from": "{from}", "to": "{to}"}, "items": "shifts"
  },
  "current": {
    "method": "POST", "path": "/api/v1/duty-schedules:batch-current",
    "body": {"scheduleUuids": "{schedule_ids}"}, "items": "duties"
  }
}
```

`method` is `GET` or a data-reading `POST`. `path` is appended to the base URL; `params` become query parameters; `body` is the POST JSON. `items` selects the array or object: use `result.teams` for `{"result":{"teams":[]}}`. If the response itself is an array, leave `items` empty or use `$`.

| Variable | Value |
|---|---|
| `{team_id}` | External ID from `team_fields.id`; available in `team`, `shifts` and individual `user` requests. |
| `{user_id}` | External person ID for individual `user` requests. |
| `{from}`, `{to}` | Window boundaries for catalog, details, profile and shift requests. |
| `{schedule_ids}` | External schedule ID array for `current`. |
| `{schedule_id}` | One schedule ID with `current_fetch: per_schedule`. |

In `{"scheduleUuids":"{schedule_ids}"}`, the whole value is replaced with a JSON array. URL variables are encoded automatically.

`user_fetch: per_user` requests individual profiles; `all` loads a paginated directory and selects people by ID. `current_fetch: batch` requests up to 500 schedules at a time; `per_schedule` requests each schedule separately and accepts an object or a one-element array.

### Pagination

| `pagination.mode` | Choose when | Completion condition |
|---|---|---|
| `none` | One response contains all records. | One request. |
| `cursor` | The response supplies a next-page token. | Missing or empty next token. |
| `offset` | The API accepts offset and page size. | Fewer records than `size`. |
| `page` | The API accepts page number and page size. | Fewer records than `size`. |

`parameter` names the token/offset/page parameter; `size_parameter` names page size. Use `start: 1` for one-based page numbering. `next_path` locates the cursor in the response. Org-service uses `pageToken`, `pageSize`, `nextPageToken`, with at most 100 records per page.

Repeated cursors and reaching `max_pages` fail the import. `null` or an error object in place of an array is not treated as a successful empty result.

## Adapting another API: field mapping

The left side names an IR field; the right side gives a path inside the external response. For this profile:

```json
{"uuid":"person-1","contacts":{"email":"anna@example.com"},"firstname":"Anna","lastname":"Petrova"}
```

the `user_fields` value can be:

```json
{
  "id": "uuid",
  "email": "contacts.email",
  "name": {"paths": ["firstname", "lastname"], "join": " "}
}
```

This is **only the `user_fields` value**. Replace that part of the mapping JSON and keep the other sections. IR receives ID `person-1`, email `anna@example.com` and name `Anna Petrova`.

| Section | Meaning | Main IR fields |
|---|---|---|
| `team_fields` | Team catalog entry | `id`, `name`, `description`. |
| `detail_fields` | Additional `team` details | `name`, `description`, `enabled`. |
| `team_filter` | Catalog field that must be nonempty | `enrolledScopeUuid` for org-service. |
| `members` | Team member array | `path` plus `fields` with `id`; optional `name`, `username`, `email`, `inactive`. |
| `responsible` | Responsible person's object | `path` and member-like `fields`, or `null` if unused. |
| `schedules` | Schedule slot array | `path` plus `fields`: `id`, optional `name`, `timezone` (defaults to UTC). |
| `user_fields` | Profile returned by `user` | `id`, `email`, `username`, `name`, `phone`, `inactive`. |
| `shift_fields` | One shift | `id`, `schedule_id`, `user_id`, `start`, `end`, `title`, `unavailable`, `inactive`. |
| `replacements` | Replacements inside a shift | `path` plus `fields`: `id`, `user_id`, `start`, `end`, `precedence`, `inactive`; an empty array means none. |
| `current_fields` | Actual duty | Schedule `id`, `status`, `user_id`; optional `valid_until`, `start`, `end`. |
| `team_matches` | Explicit team matches | For example, `{"external-team-1":42}`, where 42 is an IR team ID. |

Use dotted paths such as `employee.employeeUuid` and `person.inactive`. A numeric segment selects an array index, such as `contacts.0.email`. `$` selects the complete value.

Other mapping options:

```json
{
  "timezone": {"value": "UTC"},
  "inactive": {"path": "state", "values": {"enabled": false, "disabled": true}},
  "phone": {"path": "contacts.phone", "default": null}
}
```

`value` supplies a constant. `values` translates external values into IR values. `default` handles missing fields or unmatched translations. `inactive` and `unavailable` must resolve to JSON booleans, not strings. Timestamps need a timezone, for example `2026-11-10T09:00:00+03:00`.

Org-service identifies a team by **`enrolledScopeUuid`**, not the CMDB `externalId`. Filtering on this field includes enrolled teams; filtering by eligibility or schedule type can exclude some already enrolled teams. People use `employeeUuid`/`uuid`, and rotations use schedule UUIDs.

## Calendar versus actual duty

One external `scheduleUuid` becomes one IR rotation. Two parallel team slots create two rotations. IR stores concrete intervals without expanding recurrence again. Higher numerical replacement precedence wins; overlapping shifts in one slot do not select an arbitrary person.

The calendar shows imported intervals. With `current` configured, actual assignment uses its response:

| Status | Meaning |
|---|---|
| `active` | Assign the known active person. |
| `gap` | No assignee in the slot. |
| `unavailable` | The person is unavailable. |
| `ambiguous` | The source could not determine a unique assignee. |
| `stale` in IR | No fresh response yet, or the previous response expired. |

The last four states do not assign someone from stale data. Normal IR routing/escalation behavior follows. Without `current`, assignment follows imported shifts and replacements. Permitted local edits and ordinary rotation overrides also apply.

Responses remain usable for at most `current_max_age_seconds`, default 120, configurable in mapping JSON. `valid_until` and the effective end can shorten this period. After an API failure, the previous answer is usable only until expiry. Current duty refresh runs separately from full imports and accounts for absence changes without relying on schedule revisions.

Pausing periodic synchronization retains the calendar but lets current-duty data expire. With local editing enabled, use **Imported schedule** in the rotation actions to edit shifts and replacements. This form uses UTC times.

## Connecting to an internal API

The server calls the external API. A successful request from your laptop does not establish access from IR's container or host.

1. Check DNS, routing and API port access from web and scheduler.
2. Add the API IP/subnet to server configuration, for example:

   ```ini
   [orchestration]
   webhook_private_network_allowlist = 10.20.30.0/24
   ```

3. Restart IR processes to reload configuration.
4. Select server-allowed networks in the source (`private_network_policy: allowlist`).
5. For an internal CA, install trust in the IR processes' environment. To connect without verifying the certificate, enable **Skip TLS certificate verification** in the source and save its settings.

The API setting is `config.verify_tls`: `true` (the default) enables verification; `false` disables it. It applies to response samples, previews, imports and current-duty refreshes. After changing it, fetch and apply a new preview before re-enabling periodic synchronization. This setting does not bypass the server allowlist or affect other sources or outbound webhooks.

Separate multiple subnets with commas. Plain HTTP also requires `webhook_allow_http = true` in that section. Selecting allowlist in the form does not add addresses to the server list: this uses IR's existing outbound network policy.

Check DNS, TCP and TLS in a standard Docker deployment without sending a PAT:

```bash
docker exec incidentrelay curl --noproxy '*' -sS -o /dev/null -w 'HTTP %{http_code}\n' \
  --connect-timeout 10 --max-time 20 \
  'https://example.com/api/v1/support-team-catalog?pageSize=1'
```

Replace the URL with your API address and repeat for `incidentrelay-scheduler`: web fetches response samples, while scheduler runs imports. HTTP 401/403 is expected without a PAT and confirms an HTTP connection, but does not validate token permissions or the API path. `Could not resolve host` indicates a DNS failure; `Connection refused` indicates a rejected connection; a timeout means no response arrived within the limit. Certificate verification failures require configuring internal CA trust in both containers. `--noproxy '*'` checks a direct connection, matching synchronization's transport, which does not use `HTTP_PROXY`/`HTTPS_PROXY`. A successful curl request does not validate IR's server allowlist.

## Connecting a script to IR

Use the **IR base URL**, destination group ID and a personal token owned by an administrator of that group. Grant `directory-sync:read` and `directory-sync:write`. Legacy `resources:*` and team-bound tokens cannot manage these sources.

To check the connection, with the **IR token** in the `IR_TOKEN` environment variable:

```bash
curl --fail-with-body 'https://ir.example.com/api/admin/directory-sync/options' \
  -H "Authorization: Bearer ${IR_TOKEN}"
```

The response contains accessible `groups`, `teams` and a ready `preset` configuration. These group/team IDs are local IR IDs, not external UUIDs.

| Request | Purpose |
|---|---|
| `GET /api/admin/directory-sync` | List accessible sources and IDs. |
| `POST /api/admin/directory-sync` | Create with `name`, `group_id`, `config`, `headers`, `enabled: false`. Use the modified `preset` object as `config`. |
| `GET /api/admin/directory-sync/{id}` | Read configuration, current `revision`, results and job status. Secrets are not returned. |
| `PUT /api/admin/directory-sync/{id}` | Update with the current `revision`. Omit `headers` to preserve credentials. |
| `POST /api/admin/directory-sync/{id}/sample` | Inspect catalog response shape. |
| `POST /api/admin/directory-sync/{id}/preview` | Queue a preview with `{"revision":1}`. |
| `POST /api/admin/directory-sync/{id}/apply` | Apply with `revision` and the resulting `preview_token`. |
| `POST /api/admin/directory-sync/{id}/run` | Import an approved configuration with its `revision`. |

Execution endpoints return **202**, meaning queued. Poll the source: `pending_mode` and `running` indicate unfinished work; `last_error` holds failures, `preview_result` holds the preview and `last_result` holds the application result. Current-duty failures use `current_error`. The full schema is available in IR OpenAPI.

Concrete shift endpoints reuse rotation permissions: `GET/POST /api/rotations/{rotation_id}/imported-shifts`, `PUT/DELETE /api/rotations/imported-shifts/{shift_id}`. Lists use `after`/`next_cursor`; `user_id` is an IR user ID. Local deletion remains a tombstone until the next import.

## Troubleshooting

| Symptom | Check |
|---|---|
| Missing menu or IR API returns 403 | Group administrator role, destination group and token scopes. |
| Preview stays queued | Scheduler: `systemctl status incidentrelay-scheduler`; logs: `journalctl -u incidentrelay-scheduler -f`. Docker: `docker compose logs -f incidentrelay-scheduler`. |
| `API target blocked` | HTTPS, server allowlist and the source network policy. |
| External API returns 401/403 | PAT validity, permissions and header format. An IR token does not replace the external PAT. |
| `API DNS resolution failed` | DNS inside both web and scheduler containers. |
| `API TLS connection failed` | CA trust, certificate hostname and TLS settings in the IR environment. |
| `API connection refused` or `API connection failed` | API address, port and direct network access from IR containers. |
| `API request timed out` | Network access, API response time and `timeout_seconds`. |
| `API response exceeded the 8 MiB limit` | Reduce the API page size. |
| `items mapping must resolve to an array` | The operation's `items` path must select an array. |
| No teams in the preview | Catalog data and `team_filter`; org-service needs nonempty `enrolledScopeUuid`. |
| A team is marked `skip` | Its local match and whether managing matched teams is enabled. |
| Email conflict | Emails for everyone referenced, including leaders and replacements; duplicates and deleted matching accounts. |
| Cannot enable periodic updates | Apply a preview of the current configuration after edits. |
| `Preview expired` or `Local data changed since preview` | Fetch and review a new preview. |
| Calendar exists but no current assignee | `current_error`, current status/freshness, user activity and enabled periodic updates. |

Transient failures receive up to three attempts. Limits are 8 MiB per response, 10,000 requests and 30 minutes per run, and 100,000 records per operation. Set the 1–60 second request timeout with `timeout_seconds`. Redirects are rejected; authentication failures are not retried. Headers and raw response bodies are excluded from errors and logs.

Response sample requests report external API failures as `sync_api_error`: HTTP 502 for connection or response failures, and HTTP 504 for timeouts. HTTP 409 `sync_conflict` refers to synchronization state, such as a busy source or stale revision. Earlier versions also returned `teams: API connection failed` as `sync_conflict`; that code alone does not prove a team conflict or concurrent run. Background execution requests still return HTTP 202; read subsequent failure details from `last_error` or `current_error`.

A full import is applied in one transaction after all data has loaded. A failed request prevents a partial result from being applied. A per-source lock limits concurrent runs, and queued work survives scheduler restarts.
