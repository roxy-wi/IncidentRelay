---
title: Alert Matchers
description: Shared matcher format, editor behavior and suggestions from recent alerts.
---

# Alert Matchers

IncidentRelay uses one matcher format for routes, service rules, runbooks, silences, matcher presets, priority policy rules and notification policy rules.

All conditions in one matcher object use **AND** semantics. An empty object matches every alert:

```json
{}
```

## Match alert labels

Flat Prometheus-style keys are treated as alert labels:

```json
{
  "alertname": "DiskFull",
  "instance": "host1",
  "severity": "critical"
}
```

The structured form is equivalent:

```json
{
  "labels": {
    "alertname": "DiskFull",
    "instance": "host1",
    "severity": "critical"
  }
}
```

## Match alert fields

Use top-level `source`, `title` or `title_regex` for common alert fields:

```json
{
  "source": "alertmanager",
  "title_regex": "^Database"
}
```

Use `fields` for normalized context fields and nested resources:

```json
{
  "fields": {
    "status": "firing",
    "priority": "p1",
    "service.slug": "payments-api",
    "team.slug": "platform"
  }
}
```

## Value operators

A matcher value can be an exact value, a list or an operator object.

Match one of several values:

```json
{
  "severity": ["critical", "high"]
}
```

Match a regular expression:

```json
{
  "instance": {
    "regex": "^db-[0-9]+$"
  }
}
```

Exclude a value:

```json
{
  "environment": {
    "not": "development"
  }
}
```

Match a substring:

```json
{
  "fields": {
    "message": {
      "contains": "timeout"
    }
  }
}
```

## Matcher presets

Policy and rule editors can combine a matcher preset with additional local matchers. The preset and local matcher object both have to match.

Use `{}` when the rule should rely only on its selected preset.

## Matcher editor

The shared matcher editor provides the same JSON validation and formatting behavior on every supported page.

- **Format** validates the JSON object and formats it with indentation.
- **Suggestions** loads known matcher names and observed values from recent alerts.
- Selecting a suggestion inserts it into the current matcher object but does not save the form.
- Suggestions do not replace validation or guarantee that future alerts will contain the same values.

## Suggestion scope and privacy

Suggestions require a team and only inspect alerts accessible through that team. A route or service context can narrow the sample further.

By default, IncidentRelay inspects up to 200 recent alerts and returns up to 20 values for each matcher name. The API supports a maximum sample of 500 alerts and a maximum of 50 values per matcher name.

Suggestions include stored alert labels and normalized values such as severity, status, source and incident priority. Teams without matching alert history receive an empty suggestion list.
