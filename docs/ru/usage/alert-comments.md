---
title: Комментарии к алертам
description: Создание, просмотр, редактирование и удаление комментариев к группам алертов в IncidentRelay
---

# Комментарии к алертам

Комментарии к алертам позволяют ответственным сохранять человеческий контекст прямо внутри группы алертов: заметки о расследовании, решения, ссылки, детали передачи смены и информацию о последующих действиях.

Откройте:

    Alerts -> Alert details -> Comments

Комментарии привязываются к группе алертов. В текущем Alerts API параметр пути с именем `alert_id` — это идентификатор группы алертов, используемый эндпоинтом деталей алерта.

## Для чего нужны комментарии

Используйте комментарии для записи информации, которая должна остаться в истории алерта:

* что было проверено;
* кто ведёт расследование;
* временные шаги по смягчению последствий;
* ссылки на дашборды, логи, тикеты или runbook;
* заметки при передаче смены между ответственными;
* заметки после разрешения.

Комментарии отличаются от событий алерта. События алерта — это записи хронологии/аудита, генерируемые системой, тогда как комментарии — это заметки, написанные пользователем. Создание, редактирование или удаление комментария также записывает событие алерта, чтобы в хронологии отображалось, что произошло действие с комментарием.

## Разрешения

Чтение комментариев требует доступа на чтение алертов для команды группы алертов.

Создание, редактирование и удаление комментариев требуют доступа ответственного для команды группы алертов.

Разрешённые пользователи:

    Team responder
    Team manager
    Global admin

Пользователи, имеющие только доступ наблюдателя, могут читать комментарии, но не могут их создавать, редактировать или удалять.

## Правила для текста комментария

Текст комментария — это обычный текст.

Правила валидации:

* текст обязателен;
* текст обрезается по краям перед сохранением;
* пустой текст или текст только из пробелов отклоняется;
* максимальная длина — 5000 символов.

## Поведение UI

Блок Comments в деталях алерта должен показывать:

* существующие комментарии, упорядоченные по времени создания;
* имя автора или запасную идентификацию;
* время создания;
* пометку об изменении, когда `updated_at` позже `created_at`;
* форму добавления комментария для пользователей с разрешениями ответственного;
* кнопки Edit и Delete для пользователей с разрешениями ответственного;
* кнопку Refresh для перезагрузки комментариев без закрытия модального окна.

После создания, редактирования или удаления комментария UI должен обновить оба элемента:

* список комментариев;
* хронологию событий алерта.

## Эндпоинты API

### Список комментариев

    GET /api/alerts/{alert_id}/comments

Возвращает комментарии для группы алертов.

Требуемое разрешение:

    alert group team read access

Пример:

    curl -X GET \
      http://127.0.0.1:8080/api/alerts/123/comments \
      -H 'Authorization: Bearer API_TOKEN'

Пример ответа:

    [
      {
        "id": 10,
        "group_id": 123,
        "alert_id": null,
        "user_id": 5,
        "user": {
          "id": 5,
          "username": "alice",
          "email": "alice@example.com",
          "display_name": "Alice"
        },
        "body": "Checking RabbitMQ cluster state and network links.",
        "created_at": "2026-06-05T11:30:00",
        "updated_at": "2026-06-05T11:30:00",
        "edited": false
      }
    ]

### Создать комментарий

    POST /api/alerts/{alert_id}/comments

Требуемое разрешение:

    Team responder, Team manager, or global admin

Тело запроса:

    {
      "body": "Investigating. Disk usage increased after backup job."
    }

Пример:

    curl -X POST \
      http://127.0.0.1:8080/api/alerts/123/comments \
      -H 'Authorization: Bearer API_TOKEN' \
      -H 'Content-Type: application/json' \
      -d '{"body":"Investigating. Disk usage increased after backup job."}'

Успешный ответ:

    201 Created

    {
      "id": 11,
      "group_id": 123,
      "alert_id": null,
      "user_id": 5,
      "user": {
        "id": 5,
        "username": "alice",
        "email": "alice@example.com",
        "display_name": "Alice"
      },
      "body": "Investigating. Disk usage increased after backup job.",
      "created_at": "2026-06-05T11:35:00",
      "updated_at": "2026-06-05T11:35:00",
      "edited": false
    }

Ошибка валидации:

    400 Bad Request

    {
      "error": "validation_error",
      "message": "comment body is required"
    }

### Обновить комментарий

    PUT /api/alerts/{alert_id}/comments/{comment_id}

Обновляет существующий неудалённый комментарий в группе алертов.

Требуемое разрешение:

    Team responder, Team manager, or global admin

Тело запроса:

    {
      "body": "Updated investigation note. Backup job is confirmed as the trigger."
    }

Пример:

    curl -X PUT \
      http://127.0.0.1:8080/api/alerts/123/comments/11 \
      -H 'Authorization: Bearer API_TOKEN' \
      -H 'Content-Type: application/json' \
      -d '{"body":"Updated investigation note. Backup job is confirmed as the trigger."}'

Успешный ответ:

    200 OK

    {
      "id": 11,
      "group_id": 123,
      "alert_id": null,
      "user_id": 5,
      "user": {
        "id": 5,
        "username": "alice",
        "email": "alice@example.com",
        "display_name": "Alice"
      },
      "body": "Updated investigation note. Backup job is confirmed as the trigger.",
      "created_at": "2026-06-05T11:35:00",
      "updated_at": "2026-06-05T11:42:00",
      "edited": true
    }

### Удалить комментарий

    DELETE /api/alerts/{alert_id}/comments/{comment_id}

Удаляет комментарий из видимого списка комментариев. Рекомендуемая реализация — мягкое удаление, чтобы сохранялась историческая целостность.

Требуемое разрешение:

    Team responder, Team manager, or global admin

Пример:

    curl -X DELETE \
      http://127.0.0.1:8080/api/alerts/123/comments/11 \
      -H 'Authorization: Bearer API_TOKEN'

Успешный ответ:

    200 OK

    {
      "deleted": true,
      "id": 11
    }

## События и аудит

Действия с комментариями должны создавать события алерта:

Action Event type
Create `commented`
Update `comment_updated`
Delete `comment_deleted`

Действия с комментариями также должны записывать записи аудита:

Action Audit action
Create `alert_group.comment`
Update `alert_group.comment.update`
Delete `alert_group.comment.delete`

## Устранение неполадок

Если комментарии не видны:

1. Проверьте, что группа алертов существует.
2. Проверьте, что пользователь может читать команду группы алертов.
3. Проверьте, что удалённые комментарии отфильтрованы из запроса списка по умолчанию.
4. Проверьте консоль браузера на наличие ошибок фронтенда.
5. Проверьте, что `GET /api/alerts/{alert_id}/comments` возвращает JSON.

Если создание, редактирование или удаление комментариев завершается ошибкой:

1. Проверьте, что у пользователя есть роль Team responder или Team manager.
2. Проверьте, что запрос содержит `Content-Type: application/json`.
3. Проверьте, что `body` не пустой.
4. Проверьте, что `body` не длиннее 5000 символов.
5. Проверьте логи сервера по `error_id`, если API возвращает неожиданную ошибку.
