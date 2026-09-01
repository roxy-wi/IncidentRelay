---
title: Интеграции
description: Источники входящих алертов и исходящие каналы уведомлений
---

# Интеграции

В IncidentRelay есть два разных уровня интеграций. При настройке или устранении неполадок держите их отдельно.

```text
Monitoring system -> Incoming integration -> Route -> Notification channels -> User action
```

Браузерные push-уведомления на уровне профиля отделены от каналов уведомлений. Пользователи включают браузерные/PWA push-уведомления в разделе «Профиль», и алерты доставляются на активные устройства с браузерными push-уведомлениями назначенного пользователя. Подробнее: [Браузерные push-уведомления](../usage/browser-push.md).

## Входящие интеграции алертов

Входящие интеграции создают или обновляют алерты в IncidentRelay. Они выбираются по полю маршрута `source` и требуют токен приёма маршрута (route intake token).

| Источник            | Эндпоинт                                   | Документация                                              |
|---------------------|--------------------------------------------|-----------------------------------------------------------|
| Alertmanager        | `POST /api/integrations/alertmanager`      | [Alertmanager](alertmanager.md)                           |
| AWS SNS/Cloud watch | `POST /api/integrations/aws-sns`           | [AWS SNS/Cloud watch](aws-sns-cloudwatch.md)              |
| Grafana             | `POST /api/integrations/grafana`           | [Grafana](grafana.md)                                     |
| Datadog             | `POST /api/integrations/datadog`           | [Datadog](datadog.md)                                     |
| New Relic           | `POST /api/integrations/new-relic`         | [New Relic](new-relic.md)                                 |
| Nagios              | `POST /api/integrations/nagios`            | [Nagios](nagios.md)                                       |
| Uptime Kuma         | `POST /api/integrations/uptime-kuma`       | [Uptime Kuma](uptime-kuma.md)                             |
| RMON                | `POST /api/integrations/rmon`              | [Grafana](rmon.md)                                        |
| Zabbix              | `POST /api/integrations/zabbix`            | [Zabbix](zabbix.md)                                       |
| Sentry              | `POST /api/integrations/sentry/<route_id>` | [Sentry](sentry.md)                                       |
| LibreNMS            | `POST /api/integrations/librenms`          | [LibreNMS](librenms.md)                                   |
| Generic webhook / PagerDuty Events API v2 | `POST /api/integrations/webhook` | [Универсальный вебхук](generic-webhook.md) |

Токены приёма маршрута принадлежат маршрутам, а не каналам. Сначала создайте маршрут, скопируйте его токен приёма и используйте этот токен в системе мониторинга.

## Каналы уведомлений

Каналы уведомлений доставляют алерты после того, как маршрут сопоставил входящий алерт.

| Тип канала      | Назначение                                                                     | Документация                                  |
|-----------------|--------------------------------------------------------------------------------|-----------------------------------------------|
| Mattermost      | Уведомления в чате, опциональные кнопки ACK/Resolve, обновления сообщений       | [Канал Mattermost](mattermost.md)             |
| Telegram        | Уведомления через Telegram Bot API, опциональные inline-действия                | [Канал Telegram](telegram.md)                 |
| Email           | Отправляет письмо на email из профиля назначенного пользователя                 | [Канал Email](email.md)                       |
| Slack           | Уведомления через входящий webhook или Bot API с действиями ACK/Resolve и обновлениями | [Канал Slack](slack.md)                      |
| Discord         | Отправляет уведомления в вебхук Discord                                         | [Каналы на основе вебхуков](webhook-channels.md) |
| Microsoft Teams | Отправляет уведомления в вебхук Teams                                           | [Каналы на основе вебхуков](webhook-channels.md) |
| Webhook         | Отправляет payload уведомления на пользовательский HTTP-эндпоинт                | [Каналы на основе вебхуков](webhook-channels.md) |
| Voice call      | Звонит на телефон назначенного пользователя через глобально настроенного голосового провайдера | [Канал голосовых вызовов](voice-call.md)      |

Сначала прочитайте про общее поведение каналов: [Каналы уведомлений](channels.md).

## Обычный порядок настройки

```text
1. Create a group
2. Create users and fill contact fields, such as email, phone, Telegram ID
3. Optional: configure browser push and ask users to enable it in Profile
4. Create a team
5. Create a rotation and assign on-call users
6. Create notification channels
7. Create a route and attach channels
8. Copy the route intake token
9. Configure Alertmanager, Zabbix, or webhook sender
10. Send a test alert
11. Verify notification delivery and ACK/Resolve flow
```

## Направление устранения неполадок

Когда алерт не уведомляет пользователя через канал, проверьте цепочку по порядку:

```text
Incoming payload -> route match -> route channels -> channel severity filter -> notifier -> external provider
```

Для браузерных push-уведомлений проверяйте вместо этого цепочку на уровне профиля:

```text
alert assignee -> assignee has active browser push subscription -> service worker/browser notification
```

Если тестовое уведомление в канал работает, а реальные алерты — нет, проблема обычно в сопоставлении маршрута, привязке канала к маршруту, фильтрации по severity, отсутствии контактных данных ответственного или в правиле заглушки (silence).

Если тест браузерного push-уведомления работает, а push реального алерта — нет, проверьте, что алерт назначен тому же пользователю, который включил push в разделе «Профиль».
