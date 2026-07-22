---
title: Шаблоны Email
description: Настройка шаблонов email-уведомлений IncidentRelay.
---

# Шаблоны email

Каналы Email могут определять опциональный HTML-шаблон.

Если пользовательский шаблон не настроен, IncidentRelay использует встроенный макет email по умолчанию.

## Формат плейсхолдеров

Используйте плейсхолдеры в стиле Python:

```html
<h1>{event_type}: {title}</h1>
<p>{message}</p>
```

Не используйте плейсхолдеры в стиле mustache, такие как `{{ title }}`.

## Доступные плейсхолдеры

| Плейсхолдер | Описание |
|---|---|
| `{event_type}` | Событие уведомления, например `NOTIFICATION`, `ACKNOWLEDGED`, `RESOLVED` |
| `{title}` | Заголовок алерта |
| `{message}` | Сообщение алерта |
| `{alert_id}` | ID алерта в IncidentRelay |
| `{team}` | Slug или имя команды |
| `{status}` | Статус алерта |
| `{severity}` | Нормализованный уровень важности алерта |
| `{assignee}` | Отображаемое имя или имя пользователя назначенного лица |
| `{source}` | Источник алерта, например `alertmanager`, `zabbix`, `webhook` |
| `{alert_url}` | Ссылка на алерт в IncidentRelay |
| `{text}` | Сообщение алерта в текстовом формате |

Значения, вставляемые в HTML-шаблон, должны экранироваться рендерером.

## Пример

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

## Сброс к настройкам по умолчанию

Чтобы использовать встроенный макет по умолчанию, оставьте шаблон пустым или сбросьте его в интерфейсе.
