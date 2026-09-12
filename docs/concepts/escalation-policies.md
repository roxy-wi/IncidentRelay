---
title: Escalation Policies
description: Configure multi-step alert escalation chains in IncidentRelay
---

# Escalation Policies

Escalation policies define a multi-step escalation chain for alerts routed to a team.

A policy belongs to one team and contains ordered rules. Each rule defines:

- the escalation order;
- the delay before moving to the next rule;
- the target type;
- the target object.

Supported target types:

| Target type | Meaning |
|---|---|
| `rotation` | Assign the alert to the current on-call user from the selected rotation |
| `user` | Assign the alert to a specific team user |

Example:

```text
Policy: Critical escalation

Rule 1:
  Target: Primary rotation
  Delay: 300 seconds

Rule 2:
  Target: Backup rotation
  Delay: 600 seconds

Rule 3:
  Target: Team lead user
  Delay: 900 seconds
```

## Route escalation modes

A route can work in one of two modes.

### Simple rotation mode

The route points directly to a rotation.

```text
Route -> Rotation -> Team reminder-based escalation
```

In this mode, IncidentRelay uses the team settings:

- `Simple rotation escalation`;
- `Simple escalation after reminders`.

Reminders continue while the alert is firing, as long as the assigned rotation has reminders enabled.

### Escalation policy mode

The route points to an escalation policy.

```text
Route -> Escalation policy -> Rules
```

In this mode, IncidentRelay uses policy rules and rule delays.

Team reminder-based escalation is ignored for this route:

```text
Team escalation_enabled         ignored
Team escalation_after_reminders ignored
```

Reminders can still be sent between policy steps to the current escalation target. After the policy has completed all rules and all allowed repeats, reminders stop for that alert. The alert remains `firing` until it is acknowledged or resolved.

## Repeat count

`repeat_count` controls how many additional full policy cycles are allowed after the first pass through all rules.

| Value | Meaning |
|---:|---|
| `0` | Run all rules once, then stop policy reminders |
| `1` | Run all rules once, then repeat the complete rule chain one more time |
| `2` | Run all rules once, then repeat the complete rule chain two more times |

Example with two rules and `repeat_count = 1`:

```text
Rule 1 -> Rule 2 -> Rule 1 -> Rule 2 -> stop
```

## Reminder behavior

Policy escalation and reminders are related but separate.

| Route mode | What controls reminders | What controls escalation |
|---|---|---|
| Simple rotation | Rotation reminder interval | Team `Simple escalation after reminders` |
| Escalation policy | Rotation reminder interval of the current target | Policy rule delay |

If a route uses an escalation policy:

- reminders continue while the policy still has a next rule or repeat cycle;
- reminders stop after the policy is exhausted;
- team reminder-based escalation does not run.

If a route does not use a policy:

- the old reminder-based rotation behavior is used;
- reminders can continue indefinitely until the alert is acknowledged, resolved, silenced, shelved or assigned through a rotation with reminder interval `0`.

## Alert state

Alerts created from a policy route store the current policy state:

| Field | Meaning |
|---|---|
| `escalation_policy_id` | Policy used by the route |
| `escalation_rule_id` | Current rule |
| `escalation_level` | Number of policy escalations already performed |
| `escalation_repeat_count` | Completed policy repeat cycles |
| `next_escalation_at` | When the next policy step should run |
| `last_escalated_at` | Last policy escalation timestamp |

This state is shown in alert details so users can see which policy rule currently owns the alert.

## Permissions

Escalation policies use team permissions.

| Role | Access |
|---|---|
| Team viewer | View policies and rules |
| Team responder | View policies and rules |
| Team manager | Create, update and delete policies and rules |
| Group editor | Can manage policies for teams they can write |
| Global admin | Full access |

## Recommended setup flow

```text
1. Create a team
2. Create rotations and add members
3. Create notification channels
4. Create an escalation policy
5. Add policy rules
6. Create or edit a route
7. Set Escalation mode = Escalation policy
8. Select the policy
9. Attach route channels
10. Send a test alert
```

## Example

```text
Team: Cloud OPS

Policy: Critical escalation
Repeat count: 1

Rule 1:
  Target type: rotation
  Target: Primary rotation
  Delay: 300

Rule 2:
  Target type: rotation
  Target: Backup rotation
  Delay: 600

Rule 3:
  Target type: user
  Target: cloud-lead
  Delay: 900
```

Timeline:

```text
12:00 alert created -> Primary rotation user notified
12:05 no ACK -> Backup rotation user notified
12:15 no ACK -> cloud-lead notified
12:30 repeat cycle starts, if repeat_count allows it
```
