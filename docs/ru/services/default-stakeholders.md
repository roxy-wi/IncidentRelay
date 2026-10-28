---
title: Подписчики сервиса по умолчанию
description: Независимый снимок ServiceOwner при создании операционного Incident.
---

# Подписчики сервиса по умолчанию

При создании операционного Incident с основным сервисом активные ServiceOwner
копируются в его stakeholders. Снимок включает пользователя, роль и флаги
уведомлений. Последующее изменение настроек сервиса не переписывает Incident.

Создание AlertGroup, привязка группы к существующему Incident, смена основного
сервиса и добавление affected service не создают новый снимок владельцев.
В существующем Incident можно отдельно добавить или деактивировать подписчика;
его публичный API не редактирует notification flags.

Роль владельца (`owner`, `stakeholder`, `business_owner`, `support`,
`customer_success`, `executive`, `custom`) сохраняется в снимке. Роли ручного
добавления через Incident API ограничены отдельно.

| Флаг | Операционное событие |
|---|---|
| `notify_on_created` | Создание Incident |
| `notify_on_priority_change` | Изменение приоритета Incident |
| `notify_on_status_change` | Изменение workflow Incident |
| `notify_on_resolved` | Incident переведён в resolved |
| `notify_on_comment` | Новый комментарий Incident |

Технические ACK/resolve и комментарии AlertGroup не вызывают эти события.
Resolve связанной группы автоматически не завершает Incident. Автор события
исключается из собственного stakeholder-уведомления.

Доступны email и browser push активному пользователю с пригодной подпиской;
внешний email-адресат получает только email. Push информационный, без кнопок
технического ACK/resolve. Уведомление содержит название, приоритет, workflow и
ссылку на Incident. Каналы повторяются независимо через существующий scheduler;
см. [гарантии доставки](../incidents/stakeholders.md#доставка-и-повторы).

## API настроек сервиса

Список: `GET /api/services/<service_id>/owners`.
Создание: `POST /api/services/<service_id>/owners`.
Изменение: `PUT /api/services/<service_id>/owners/<owner_id>`.

```json
{
  "user_id": 42,
  "role": "business_owner",
  "active": true,
  "notify_on_created": true,
  "notify_on_priority_change": true,
  "notify_on_status_change": false,
  "notify_on_resolved": true,
  "notify_on_comment": true
}
```

`DELETE /api/services/<service_id>/owners/<owner_id>` деактивирует настройку:

```json
{"deleted": true, "id": 10}
```

Существующие снимки Incident при этом не меняются.
