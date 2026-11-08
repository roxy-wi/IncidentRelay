---
title: Центр уведомлений
description: Ожидающие запросы responder операционного Incident.
---

# Центр уведомлений

`GET /api/notification-center?limit=20` возвращает `items` и `unread_count`.
`limit` — от 1 до 100. Это ожидающие запросы Incident, на которые пользователь
может ответить. `unread_count` равен числу возвращённых записей: это не отметка
прочтения и не размер очереди доставки.

Запись содержит ID `responder-request-<id>`, тип `responder_request`, title, body,
время, `incident_id`, объект `responder` и описания действий. Вложенного объекта
`incident` в ответе 2.5 нет. Ссылка `url` открывает `/incidents/<incident_id>`.

```http
PUT /api/incidents/17/responders/8
Content-Type: application/json

{"status":"accepted"}
```

Для отказа передавайте `declined`. После выхода из `requested` запрос исчезает из
списка. При выполнении действия права и состояние проверяются заново; конкурентный
ответ или истечение срока могут привести к `409`. После действия обновите список.

Верхнеуровневые timestamps записи сейчас содержат UTC без гарантированного суффикса
часового пояса; timestamps вложенного responder имеют явный UTC. Не трактуйте
верхнеуровневое время как местное время браузера.

Подробнее: [responders](responders.md).
