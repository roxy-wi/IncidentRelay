---
title: Troubleshooting
description: Common IncidentRelay operational problems and checks.
---

# Troubleshooting

## 500 on duplicate names or slugs

Duplicate resources should return `409 Conflict`, not `500`. Check API logs for `IntegrityError` and add explicit error handling in the corresponding view.

Common examples:

- duplicate group slug;
- duplicate team slug;
- duplicate service slug inside the same team;
- duplicate channel name inside the same team.

## Empty body returns unclear validation error

POST/PUT endpoints should return a structured `400 validation_error` when body is missing or invalid JSON.

## Calendar invalid date returns 500

Query parameters such as `start` and `end` should be validated before date parsing reaches business logic.

## Email test works but real alert does not

Check:

1. Real alert has an assignee.
2. Assigned user has email in profile.
3. Channel is attached to the matched route.
4. Severity filter allows the alert severity.
5. SMTP relay accepted and delivered the message.

## Voice call fails with missing phone

Voice call sends to the assigned user's profile phone number. Set `phone` on the assigned user.

## Telegram token error

Telegram bot token must contain a colon:

```text
123456789:AA...
```

If the token is invalid, fix the channel config or disable the channel.

## Reminders are duplicated

Check that only one scheduler process is running and that scheduler is not started inside every web worker.

## Alert is not visible

Check:

1. The correct route intake token was used.
2. The endpoint matches the route source.
3. Route matchers match alert labels.
4. The group is active.
5. The team is active.
6. The UI active group is correct.
7. `All my groups` is selected when the alert can belong to another accessible group.
8. `routing_error` in the integration response.
9. JSON logs by `error_id` if the server returned one.

## Alert has no service

If an alert is created but service is empty:

1. Check that the route has a default service.
2. Check that a service match rule exists.
3. Check that the service match rule is enabled.
4. Check that the rule is scoped to the correct route, or has no route scope.
5. Check that labels, annotations or payload fields match the rule.
6. Check that the service and owning team are enabled.

Example Alertmanager service match rule:

```json
{
  "labels": {
    "job": "RabbitMQ",
    "rabbitmq": {
      "op": "regex",
      "value": "^rabbitmq-cloud$"
    }
  }
}
```

## Service links or runbooks are not shown in notifications

Check:

1. The alert has `service_id`.
2. The service link or runbook is enabled.
3. The service link or runbook is not deleted.
4. The runbook matchers are empty, or they match the alert labels/annotations/payload.
5. The notification formatter supports service context for the selected channel.

Runbook matcher behavior:

```text
empty matchers -> generic runbook for all alerts of the service
matchers set -> only matching alerts
```

## Browser push is disabled or VAPID public key is not configured

Check the profile config endpoint:

```text
GET /api/profile/push/vapid-public-key
```

Expected response:

```json
{
  "enabled": true,
  "public_key": "B..."
}
```

If `enabled` is false or `public_key` is null, fix the `[browser_push]` config and restart the web service. Restart the scheduler too if it sends notifications in your installation.

## Browser push test works but real alert does not

Test push sends to the current profile user. Real alert push sends to `alert.assignee_id`.

Check:

1. The alert has an assignee.
2. The assignee is the same user who enabled push in Profile.
3. The subscription row has `enabled = true` and `deleted = false`.
4. Browser push is enabled in config.
5. `/service-worker.js` is current in the user's browser.

Browser push is not a channel, so it does not appear in route channel bindings.

## Browser push action returns token_expired

The one-time ACK/Resolve token was older than `[browser_push] action_token_ttl_seconds` when the browser sent the action.

## Browser push action returns token_already_used

The same notification action token was already consumed. This can happen after a double click, browser retry, or clicking the same notification action more than once.

## Service, team or group name shows as `-`

Display code should use this order:

```text
name -> slug -> "-"
```

For links and runbooks, make sure serializers include:

```text
service_id
service_name
service_slug
team_id
team_name
team_slug
```
