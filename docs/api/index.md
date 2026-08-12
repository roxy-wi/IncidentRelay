---
title: API
description: IncidentRelay API overview, authentication and endpoint groups.
---

# API

Swagger UI is available at:

```text
/docs
```

OpenAPI JSON is available at:

```text
/api/openapi.json
```

Use route intake tokens for incoming integration endpoints and personal API tokens for user-scoped automation.

## Browser push API

Browser push profile endpoints are user-scoped and require authentication:

```text
GET    /api/profile/push/vapid-public-key
GET    /api/profile/push/subscriptions
POST   /api/profile/push/subscriptions
DELETE /api/profile/push/subscriptions/{subscription_id}
POST   /api/profile/push/test
```

Push notification action endpoint is public by design and uses a one-time action token from the notification payload:

```text
POST /api/push/actions
```

Read more: [Browser Push](../usage/browser-push.md).

## More API documentation

1. [Event Orchestration API](event-orchestration.md)
2. [Services API](services.md)
3. [Escalation Policies API](escalation-policies.md)
4. [Matcher Suggestions API](matchers.md)
5. [Sentry Integration API](sentry-integration.md)
6. [Voice Call OpenAPI Notes](voice-call-openapi.md)
7. [Business services](business-services.md)

- [Heartbeats API](heartbeats.md)
