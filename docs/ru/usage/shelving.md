---
title: Откладывание алертов (Shelving)
description: Временная пауза уведомлений и эскалации для одного AlertGroup без изменения технического статуса.
---

# Откладывание алертов (Shelving)

Shelving позволяет временно убрать один существующий AlertGroup из активного цикла внимания, не меняя техническое состояние алерта.

Отложенный AlertGroup остаётся `firing` или `acknowledged`. IncidentRelay продолжает принимать дочерние алерты, писать события, выполнять корреляцию и рассчитывать влияние на сервисы/бизнес-сервисы, но приостанавливает уведомления до окончания shelving.

## Отличие от других действий

| Действие | Значение |
| --- | --- |
| Acknowledge | Инженер взял алерт в работу. |
| Shelve | Временно отложить только этот AlertGroup и вернуться к нему позже. |
| Silence | Подавлять алерты, совпадающие с правилом/matcher. |
| Maintenance | Плановое подавление в заданном scope на время обслуживания. |
| Resolve | Техническая проблема больше не активна. |

Shelving специально не является новым статусом AlertGroup.

## Что приостанавливается

Во время shelving IncidentRelay подавляет начальные уведомления, обновления, reminders, escalation и ожидающие пользовательские доставки этих событий.

Приём событий, история, корреляция, service/business impact и source-driven resolve продолжают работать.

Если AlertGroup разрешился во время shelving, shelving закрывается и по истечении времени ничего не активируется повторно.

## Web UI

В Alert Details нажмите **Shelve**, выберите 30 минут, 1, 2, 4, 8 или 24 часа и при необходимости укажите причину. Для досрочного возврата используйте **Unshelve**. На странице Alerts есть фильтр только по отложенным группам.

## Кнопки в уведомлениях

- Telegram: **Shelve 1h** / **Unshelve**;
- Slack Bot API: **Shelve 1h** / **Unshelve**;
- Mattermost Bot API: **Shelve 1h** / **Unshelve**;
- Browser Push: **Shelve 1h**; после Shelve подтверждающее уведомление предоставляет **Unshelve** и **Resolve**.

Внешний пользователь должен быть связан с пользователем IncidentRelay и иметь обычные responder-права на команду AlertGroup.

## Окончание shelving

Если после expiry/Unshelve группа всё ещё `firing`, IncidentRelay ставит в очередь одно уведомление с актуальным состоянием и начинает escalation заново от момента Unshelve. `acknowledged` остаётся acknowledged, а `resolved` не активируется повторно.

## API

```http
POST /api/alert-groups/{alert_group_id}/shelve
```

```json
{
  "duration_seconds": 3600,
  "reason": "Ждём завершения deployment"
}
```

```http
POST /api/alert-groups/{alert_group_id}/unshelve
```

```text
GET /api/alert-groups?shelved=1
```

## Настройки scheduler

```ini
[alerts]
shelve_lifecycle_check_interval_seconds = 30
shelve_lifecycle_batch_size = 100
```
