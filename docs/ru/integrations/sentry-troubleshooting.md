---
title: Устранение неполадок интеграции с Sentry
description: Устранение неполадок с подписями Sentry, маршрутизацией, дедупликацией и разрешением алертов.
---

# Устранение неполадок интеграции с Sentry

Это руководство охватывает распространённые проблемы с интеграцией IncidentRelay и Sentry.

## Вебхук возвращает `409 sentry_secret_not_configured`

Причина: маршрут IncidentRelay существует, но Sentry Client Secret не был сохранён в настройках маршрута.

Решение:

1. Откройте Internal Integration в Sentry.
2. Скопируйте **Client Secret**.
3. Откройте маршрут IncidentRelay.
4. Нажмите **Edit**.
5. Вставьте секрет в **Sentry webhook secret**.
6. Сохраните маршрут.

После сохранения детали маршрута должны показывать секрет Sentry как настроенный.

## Вебхук возвращает `403 sentry_signature_missing`

Причина: запрос не содержит заголовок `Sentry-Hook-Signature`.

Распространённые причины:

- вебхук был отправлен вручную без заголовка подписи;
- вместо Internal Integration использовался устаревший Sentry Webhook Plugin;
- прокси удалил заголовок.

Решение:

- используйте Sentry Internal Integration;
- проверьте конфигурацию обратного прокси и разрешите заголовок `Sentry-Hook-Signature`;
- не используйте устаревший Webhook Plugin для этой интеграции.

## Вебхук возвращает `403 sentry_signature_invalid`

Причина: IncidentRelay получил подпись, но она не совпадает с телом запроса и сохранённым для маршрута Client Secret.

Распространённые причины:

- неверный Client Secret вставлен в IncidentRelay;
- тело запроса изменено прокси до того, как достигло IncidentRelay;
- тестовый запрос сгенерирован с другим секретом;
- Sentry Internal Integration указывает на один маршрут, но Client Secret был сохранён в другом маршруте.

Решение:

1. Заново скопируйте Client Secret из того же Sentry Internal Integration, который отправляет на этот URL маршрута.
2. Снова вставьте его в маршрут IncidentRelay.
3. Сохраните маршрут.
4. Повторите попытку из Sentry.

Если перед IncidentRelay стоит прокси, убедитесь, что он передаёт сырое тело запроса без изменений.

## Вебхук возвращает `400 route_source_mismatch`

Причина: URL указывает на маршрут, у которого не `source=sentry`.

Решение:

- скопируйте URL вебхука из деталей маршрута Sentry;
- убедитесь, что источник маршрута — `Sentry`;
- обновите Webhook URL в Sentry Internal Integration.

## Вебхук возвращает `403 route_disabled`

Причина: маршрут отключён или удалён.

Решение:

- включите маршрут в IncidentRelay;
- убедитесь, что владеющая команда и группа активны.

## Алерты Sentry создаются, но не разрешаются

Для автоматического разрешения Sentry Internal Integration должна отправлять события жизненного цикла или восстановления метрик.

Проверьте, что Internal Integration включает:

- ресурс `issue` для событий `issue.resolved`, `issue.ignored` и `issue.unresolved`;
- ресурс `metric_alert` для событий `metric_alert.resolved`.

Действия правил алертов по issue обычно создают события `event_alert.triggered`. Для автоматического разрешения алерта IncidentRelay нужно отдельное событие жизненного цикла `issue.resolved`.

## Алерты направляются не той команде

Проверьте матчеры маршрута.

Полезные метки Sentry включают:

```json
{
  "project_slug": "backend-api",
  "environment": "production",
  "sentry_resource": "event_alert",
  "sentry_action": "triggered"
}
```

Рекомендуемые матчеры:

```json
{
  "labels": {
    "project_slug": "backend-api",
    "environment": "production"
  }
}
```

Если несколько маршрутов могут совпасть с одним и тем же алертом Sentry, проверьте приоритет/порядок маршрутов в IncidentRelay.

## Алерты дублируются вместо обновления

Проверьте group by и дедупликацию.

Рекомендуемый group by для алертов по issue:

```json
["project_slug", "issue_id"]
```

Рекомендуемый group by для метрических алертов:

```json
["project_slug", "sentry_alert_id"]
```

Дедупликация IncidentRelay использует нормализованный `dedup_key`, но группировка алертов и группировка в интерфейсе всё равно могут выглядеть зашумлённо, если `group_by` использует нестабильные метки, такие как `event_id`.

Избегайте группировки по:

```json
["event_id"]
```

потому что каждое событие Sentry может иметь разный event id.

## Тестирование без Sentry

Реальный запрос Sentry включает `Sentry-Hook-Signature`, который генерируется из сырого тела запроса и Sentry Client Secret.

Ручные примеры curl полезны для проверки доступности, но они не пройдут проверку подписи, если подпись не сгенерирована корректно.

Тест доступности без действительной подписи должен вернуть `403 sentry_signature_invalid` или `403 sentry_signature_missing`:

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/sentry/42' \
  -H 'Content-Type: application/json' \
  -H 'Sentry-Hook-Resource: event_alert' \
  -d '{"action":"triggered","data":{}}'
```

Успешный сквозной тест должен запускаться из Sentry Internal Integration или из подписанного тестового помощника в backend-тестах.
