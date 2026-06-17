---
title: Sentry Integration Troubleshooting
description: Troubleshoot Sentry signatures, routing, deduplication and resolves.
---

# Sentry integration troubleshooting

This guide covers common problems with the IncidentRelay Sentry integration.

## The webhook returns `409 sentry_secret_not_configured`

Cause: the IncidentRelay route exists, but the Sentry Client Secret has not been saved in the route settings.

Fix:

1. Open the Internal Integration in Sentry.
2. Copy the **Client Secret**.
3. Open the IncidentRelay route.
4. Click **Edit**.
5. Paste the secret into **Sentry webhook secret**.
6. Save the route.

After saving, route details should show the Sentry secret as configured.

## The webhook returns `403 sentry_signature_missing`

Cause: the request does not include the `Sentry-Hook-Signature` header.

Common reasons:

- the webhook was sent manually without the signature header;
- the legacy Sentry Webhook Plugin was used instead of an Internal Integration;
- a proxy stripped the header.

Fix:

- use a Sentry Internal Integration;
- check reverse proxy configuration and allow the `Sentry-Hook-Signature` header;
- do not use the legacy Webhook Plugin for this integration.

## The webhook returns `403 sentry_signature_invalid`

Cause: IncidentRelay received a signature, but it does not match the request body and the route's saved Client Secret.

Common reasons:

- wrong Client Secret pasted into IncidentRelay;
- request body changed by a proxy before reaching IncidentRelay;
- test request generated with a different secret;
- Sentry Internal Integration points to one route, but the Client Secret was saved on another route.

Fix:

1. Re-copy the Client Secret from the same Sentry Internal Integration that sends to this route URL.
2. Paste it into the IncidentRelay route again.
3. Save the route.
4. Retry from Sentry.

If a proxy is in front of IncidentRelay, make sure it forwards the raw request body unchanged.

## The webhook returns `400 route_source_mismatch`

Cause: the URL points to a route that is not `source=sentry`.

Fix:

- copy the webhook URL from the Sentry route details;
- ensure the route source is `Sentry`;
- update the Sentry Internal Integration Webhook URL.

## The webhook returns `403 route_disabled`

Cause: the route is disabled or deleted.

Fix:

- enable the route in IncidentRelay;
- verify that the owning team and group are active.

## Sentry alerts are created but not resolved

For automatic resolve, the Sentry Internal Integration must send lifecycle or metric recovery events.

Check that the Internal Integration enables:

- `issue` resource for `issue.resolved`, `issue.ignored` and `issue.unresolved` events;
- `metric_alert` resource for `metric_alert.resolved` events.

Issue alert rule actions usually create `event_alert.triggered` events. A separate `issue.resolved` lifecycle event is needed to resolve the IncidentRelay alert automatically.

## Alerts are routed to the wrong team

Check route matchers.

Useful Sentry labels include:

```json
{
  "project_slug": "backend-api",
  "environment": "production",
  "sentry_resource": "event_alert",
  "sentry_action": "triggered"
}
```

Recommended matchers:

```json
{
  "labels": {
    "project_slug": "backend-api",
    "environment": "production"
  }
}
```

If multiple routes can match the same Sentry alert, review route priority/order in IncidentRelay.

## Alerts duplicate instead of updating

Check group by and deduplication.

Recommended group by for issue alerts:

```json
["project_slug", "issue_id"]
```

Recommended group by for metric alerts:

```json
["project_slug", "sentry_alert_id"]
```

IncidentRelay deduplication uses the normalized `dedup_key`, but alert grouping and UI grouping can still look noisy if `group_by` uses unstable labels such as `event_id`.

Avoid grouping by:

```json
["event_id"]
```

because every Sentry event can have a different event id.

## Testing without Sentry

A real Sentry request includes `Sentry-Hook-Signature`, which is generated from the raw request body and the Sentry Client Secret.

Manual curl examples are useful for checking reachability, but they will not pass signature verification unless the signature is generated correctly.

Reachability test without valid signature should return `403 sentry_signature_invalid` or `403 sentry_signature_missing`:

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/sentry/42' \
  -H 'Content-Type: application/json' \
  -H 'Sentry-Hook-Resource: event_alert' \
  -d '{"action":"triggered","data":{}}'
```

A successful end-to-end test should be triggered from Sentry Internal Integration or from a signed test helper in backend tests.
