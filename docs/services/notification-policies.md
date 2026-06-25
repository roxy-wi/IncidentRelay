---
title: Notification Policies
description: Select shared notification channels for service alert events.
---

# Notification Policies

Notification policies define which shared notification channels receive events
for a service.

They are useful when several routes belong to the same logical service and
should use the same notification rules. Instead of copying channel lists to
every route, assign one notification policy to the service and configure the
route to use it.

## How notification policies work

A notification policy belongs to one team and contains ordered rules.

Each rule defines:

- the event types it handles;
- optional alert matchers;
- one or more notification channels;
- whether evaluation continues after the rule matches;
- whether the rule is enabled.

Rules are evaluated by position, starting with the lowest position.

When a rule matches, its channels are added to the delivery targets. Evaluation
then stops unless **Continue matching** is enabled for that rule.

Duplicate channels are removed before delivery.

## Event types

A rule can handle one or more event types:

| Event type     | Description                                   |
|----------------|-----------------------------------------------|
| `notification` | Initial alert notifications and alert updates |
| `reminder`     | Unacknowledged alert reminders                |
| `escalation`   | Escalation notifications                      |

Acknowledged and resolved events do not select channels again. IncidentRelay
updates the messages that were created by earlier deliveries.

This means that changing or removing a notification policy does not prevent
IncidentRelay from updating an already delivered message when the alert is
acknowledged or resolved.

## Matchers

Notification policy rules use the same matcher format as service match rules.

The shared editor can suggest label names and values from recent team alerts. See [Alert Matchers](../concepts/matchers.md).

An empty matcher object matches every alert:

```json
{}
```

Match by severity:

```json
{
  "severity": "critical"
}
```

Match by priority:

```json
{
  "priority": ["p1", "p2"]
}
```

Match by labels:

```json
{
  "labels": {
    "environment": "production",
    "namespace": {
      "regex": "^payments-"
    }
  }
}
```

Match by service or team fields:

```json
{
  "fields": {
    "service.slug": "payments-api",
    "team.slug": "platform"
  }
}
```

A catch-all rule is commonly placed last so that alerts not handled by earlier
rules still receive a notification.

## Route channel modes

A route controls how IncidentRelay combines its own channels with the matched
service notification policy.

| Mode                        | Behavior                                                      |
|-----------------------------|---------------------------------------------------------------|
| `route_only`                | Use only channels configured directly on the route            |
| `service_policy`            | Use only channels selected by the service notification policy |
| `service_policy_plus_route` | Combine service policy channels and route channels            |

Existing routes default to `route_only`, so enabling notification policies does
not change their current delivery behavior.

### No implicit fallback

`service_policy` does not fall back to route channels.

If the matched service has no policy, the policy is disabled, or no enabled rule
matches the event, no shared channel is selected by that route mode.

Use `service_policy_plus_route` when route channels should remain a fallback or
must always receive the event.

Personal notification rules, including browser push rules, are evaluated
separately from shared channel policies.

## Configure a notification policy

1. Open **Services → Notification Policies**.
2. Select **New policy**.
3. Choose the owning team.
4. Enter a name and optional description.
5. Save the policy.
6. Open the policy action menu and select **Rules**.
7. Add rules in the required evaluation order.
8. Select event types, matchers and channels for each rule.
9. Save each rule.

An enabled rule must contain at least one notification channel. A disabled rule
may be saved without channels.

## Assign a policy to a service

1. Open **Services → Service Catalog**.
2. Create or edit a service.
3. Select a value in **Notification policy**.
4. Save the service.

A service can only use an enabled notification policy owned by the same team.

A policy assigned to a service cannot be deleted. Remove the policy from all
services before deleting it.

## Configure a route

1. Open **Routes**.
2. Create or edit a route.
3. Select **Notification channel source**.
4. Choose one of:
   - **Route channels only**;
   - **Service notification policy**;
   - **Service policy + route channels**.
5. Save the route.

For service policy modes, the alert group must have a service. The service can
come from the route default service or from a matching service rule.

## Example: critical alerts and a catch-all rule

Policy rules:

1. **Critical alerts**
   - event types: `notification`, `reminder`, `escalation`;
   - matcher: `{"severity": "critical"}`;
   - channels: Mattermost and Telegram;
   - continue matching: disabled.

2. **Default alerts**
   - event types: `notification`;
   - matcher: `{}`;
   - channels: Email;
   - continue matching: disabled.

A critical alert uses Mattermost and Telegram and stops at the first rule. A
non-critical initial alert skips the first rule and uses Email.

## Example: combine several matching rules

Policy rules:

1. **Production alerts**
   - matcher: `{"labels": {"environment": "production"}}`;
   - channels: Operations Mattermost;
   - continue matching: enabled.

2. **Critical alerts**
   - matcher: `{"severity": "critical"}`;
   - channels: Emergency Telegram;
   - continue matching: disabled.

A critical production alert receives both Mattermost and Telegram delivery. A
non-critical production alert receives only Mattermost delivery.

## Disabled resources

IncidentRelay ignores:

- disabled policies;
- disabled rules;
- disabled or deleted channels.

A policy rule that does not include the current event type is skipped.

## Recommended setup

- Keep a catch-all rule last when every event should reach a shared channel.
- Use specific rules before generic rules.
- Use `continue_matching` only when channels from several rules should be
  combined.
- Use `service_policy` when the service policy is the authoritative delivery
  configuration.
- Use `service_policy_plus_route` when route-level channels must also receive
  events.
- Test reminder and escalation rules separately from initial notification rules.
