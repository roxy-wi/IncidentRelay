---
title: Управление инцидентами
description: Рабочая область Incident и границы технического AlertGroup в 2.5.
---

# Управление инцидентами

```text
Alert → AlertGroup → необязательный Incident
```

AlertGroup отвечает за группировку сигналов, состояние источника, ACK/resolve,
эскалации, технического ответственного и технические комментарии. Incident
содержит операционный workflow, assignee, commander/responders, stakeholders,
комментарии, затронутые сервисы, root cause и resolution summary.

AlertGroup может существовать без Incident; Incident — без AlertGroup. Один
Incident может связывать несколько групп, сохраняя их техническую историю.
Технический resolve не завершает и не закрывает Incident автоматически.
Повторное открытие связанной группы может вернуть Incident из `resolved` или
`monitoring` в `investigating`. Закрытие остаётся явным операционным действием.

## Рабочая область и API

Страница `/incidents/<id>` объединяет workflow, назначения, подписчиков,
комментарии, сервисы и историю. Сервер проверяет права чтения и реагирования.
Связанные AlertGroup и ресурсы сервисов дополнительно фильтруются по доступу
к команде, которой они принадлежат.

- `/api/alert-groups` — технические группы.
- `/api/incidents` — операционные Incident. Их идентификаторы не взаимозаменяемы.
- `/api/incidents/<id>/activity` — события и комментарии Incident и доступных,
  сейчас связанных AlertGroup. Сохраняются источник и автор; комментарий
  показывается один раз. Сначала новые записи; `limit` от 1 до 500, по умолчанию
  200. Постраничной навигации нет.
- `/api/incidents/<id>/comments` — только операционные комментарии.
- `/api/incidents/<id>/affected-services` — сервисы, инструкции, ссылки,
  доступные зависимости и агрегированное влияние без скрытых деталей зависимостей.

Для изменения полей Incident, статуса или assignee передавайте текущий
`row_version`. При `409` перечитайте запись и согласуйте своё изменение с новой
версией. У операций collaboration отдельные правила конфликтов. Время в API
workspace/collaboration передаётся с явным UTC; интерфейс показывает местное время.

## Документация

1. [Релиз 2.5 и выпускные проверки](release-notes-2.5.md)
2. [Миграция 2.4 → 2.5](collaboration-migration-2.5.md)
3. [Responders и participants](responders.md)
4. [Stakeholders и доставка](stakeholders.md)
5. [Подписчики сервиса по умолчанию](../services/default-stakeholders.md)
6. [Технические комментарии](../usage/alert-comments.md)
7. [Миграция API 2.3](api-migration-2.3.md) и [долгосрочный roadmap](../architecture/incident-management-v2.md)
