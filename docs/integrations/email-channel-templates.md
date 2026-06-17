---
title: Email Templates
description: Customize IncidentRelay email notification templates.
---

# Email templates

Email channels can define an optional HTML template.

If no custom template is configured, IncidentRelay uses the built-in default email layout.

## Placeholder format

Use Python-style placeholders:

```html
<h1>{event_type}: {title}</h1>
<p>{message}</p>
```

Do not use mustache-style placeholders such as `{{ title }}`.

## Available placeholders

| Placeholder | Description |
|---|---|
| `{event_type}` | Notification event, for example `NOTIFICATION`, `ACKNOWLEDGED`, `RESOLVED` |
| `{title}` | Alert title |
| `{message}` | Alert message |
| `{alert_id}` | IncidentRelay alert ID |
| `{team}` | Team slug or name |
| `{status}` | Alert status |
| `{severity}` | Normalized alert severity |
| `{assignee}` | Assigned user display name or username |
| `{source}` | Alert source, for example `alertmanager`, `zabbix`, `webhook` |
| `{alert_url}` | Link to the alert in IncidentRelay |
| `{text}` | Plain-text formatted alert message |

Values inserted into the HTML template should be escaped by the renderer.

## Example

```html
<!doctype html>
<html>
  <body>
    <h1>{event_type}: {title}</h1>
    <p>{message}</p>
    <table>
      <tr><td>Alert ID</td><td>{alert_id}</td></tr>
      <tr><td>Team</td><td>{team}</td></tr>
      <tr><td>Status</td><td>{status}</td></tr>
      <tr><td>Severity</td><td>{severity}</td></tr>
      <tr><td>Assignee</td><td>{assignee}</td></tr>
      <tr><td>Source</td><td>{source}</td></tr>
    </table>
    <p><a href="{alert_url}">Open alert</a></p>
  </body>
</html>
```

## Reset to default

To use the built-in default layout, leave the template empty or reset it in the UI.
