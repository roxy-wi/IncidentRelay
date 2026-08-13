---
title: Документация IncidentRelay
description: Документация по self-hosted сервису IncidentRelay для планирования дежурств, маршрутизации алертов и уведомлений
---

# Документация IncidentRelay

IncidentRelay — это self-hosted сервис для планирования дежурств (on-call), маршрутизации алертов и уведомлений. Он хранит команды, ротации, маршруты, каналы уведомлений, подписки на браузерные push-уведомления, подтверждения (ACK), разрешения (Resolve), напоминания и эскалации внутри вашей собственной инфраструктуры.

## Поток алертов

```text
Monitoring system
  -> Incoming integration endpoint
  -> Route intake token
  -> Route match
  -> Service
  -> Team and rotation
  -> Assigned on-call user
  -> Notification channels and profile browser push
  -> ACK / Resolve
```

Браузерные push-уведомления включаются пользователями в профиле и доставляются автоматически назначенным пользователям. Они не являются каналами маршрута.

## Способы установки

Выберите один способ установки:

| Способ | Рекомендуется для | Начните здесь |
|---|---|---|
| Docker Compose | быстрый старт, тестирование, простые self-hosted развёртывания | [Установка через Docker](getting-started/docker.md) |
| RPM package | RHEL, Rocky Linux, AlmaLinux, CentOS Stream | [Установка через RPM](getting-started/rpm-installation.md) |
| Manual systemd | развёртывание из исходников, собственное окружение Python, классическая Linux VM | [Ручная установка через systemd](getting-started/systemd.md) |

Все production-установки должны запускать два процесса:

```text
incidentrelay             # HTTP API, UI, incoming webhooks
incidentrelay-scheduler   # reminders, escalations, periodic jobs
```

Не запускайте задачи планировщика внутри каждого веб-воркера.

## Настройка

IncidentRelay читает путь к конфигурации из:

```text
INCIDENTRELAY_CONFIG_FILE
```

Пример:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

Старое имя `ONCALL_CONFIG_FILE` использовать не следует.

Подробнее: [Настройка](getting-started/configuration.md).

Для браузерных/PWA-уведомлений настройте `[browser_push]` и ключи VAPID. Подробнее: [Браузерные push-уведомления](usage/browser-push.md).

## Основные понятия

| Понятие | Описание |
|---|---|
| Group | Граница доступа и область администрирования на уровне группы |
| User | Человек, который может входить в систему, дежурить, получать уведомления, включать браузерные push-уведомления или использовать персональные API-токены |
| Team | Операционная единица внутри группы |
| Rotation | Расписание дежурств для команды |
| Route | Правило маршрутизации алертов с собственным токеном приёма |
| Channel | Цель исходящих уведомлений, например Mattermost, Telegram, email, вебхук или голосовой вызов |
| Browser push | Доставка браузерных/PWA-уведомлений на уровне профиля для назначенных пользователей |
| Alert | Алерт IncidentRelay, созданный из входящей интеграции |
| Silence | Правило, подавляющее уведомления для совпадающих новых алертов |
| Override | Временная замена участника ротации |

Подробнее:

- [Группы и RBAC](concepts/groups-and-rbac.md)
- [Команды, ротации и маршруты](concepts/teams-rotations-routes.md)
- [Токены приёма маршрутов](concepts/route-intake-tokens.md)
- [Каналы](concepts/channels.md)
- [Браузерные push-уведомления](usage/browser-push.md)
- [Напоминания и эскалации](concepts/reminders-and-escalations.md)
- [Event Orchestration](usage/event-orchestration.md)

## Сводка по RBAC

IncidentRelay использует два уровня разрешений:

| Уровень | Назначение |
|---|---|
| Group role | Определяет границу доступа и администрирование пользователей на уровне группы |
| Team role | Определяет, что пользователь может делать внутри конкретной команды |

Текущие названия ролей:

```text
Group roles: viewer, editor, user_admin
Team roles:  viewer, responder, manager
```

Важные правила:

- Пользователь должен состоять в группе, прежде чем его можно будет добавить в команду этой группы.
- Добавление пользователя в команду не добавляет пользователя в группу автоматически.
- `user_admin` может создавать пользователей только в пределах границы выбранной группы.
- `editor` может создавать команды в группе, но не управляет автоматически всеми командами.
- `manager` — это роль записи для конкретной команды.
- `responder` может подтверждать и разрешать алерты без изменения настроек команды.

Подробнее: [Группы и RBAC](concepts/groups-and-rbac.md).

## Интеграции

В IncidentRelay есть два уровня интеграций.

### Источники входящих алертов

| Источник            | Эндпоинт                                   | Документация                                              |
|---------------------|--------------------------------------------|-----------------------------------------------------------|
| Alertmanager        | `POST /api/integrations/alertmanager`      | [Alertmanager](integrations/alertmanager.md)              |
| AWS SNS/Cloud watch | `POST /api/integrations/aws-sns`           | [AWS SNS/Cloud watch](integrations/aws-sns-cloudwatch.md) |
| Grafana             | `POST /api/integrations/grafana`           | [Grafana](integrations/grafana.md)                        |
| RMON                | `POST /api/integrations/rmon`              | [Grafana](integrations/rmon.md)                           |
| Zabbix              | `POST /api/integrations/zabbix`            | [Zabbix](integrations/zabbix.md)                          |
| Sentry              | `POST /api/integrations/sentry/<route_id>` | [Sentry](integrations/sentry.md)                          |
| LibreNMS            | `POST /api/integrations/librenms`          | [LibreNMS](integrations/librenms.md)                      |
| Generic webhook     | `POST /api/integrations/webhook`           | [Generic webhook](integrations/generic-webhook.md)        |

Входящие интеграции используют токены приёма маршрутов (route intake token).

### Доставка уведомлений

| Способ доставки                          | Документация                                               |
|------------------------------------------|------------------------------------------------------------|
| Общее поведение каналов                  | [Каналы уведомлений](integrations/channels.md)          |
| Mattermost                               | [Mattermost](integrations/mattermost.md)                   |
| Telegram                                 | [Telegram](integrations/telegram.md)                       |
| Email                                    | [Email](integrations/email.md)                             |
| Slack                                    | [Slack](integrations/slack.md)                             |
| Discord, Microsoft Teams, кастомный вебхук | [Каналы на основе вебхуков](integrations/webhook-channels.md) |
| Голосовой вызов                          | [Голосовой вызов](integrations/voice-call.md)                   |
| Браузерные/PWA push                      | [Браузерные push-уведомления](usage/browser-push.md)        |

У каналов уведомлений нет токенов приёма. Маршруты получают алерты, а затем отправляют уведомления в прикреплённые каналы. Браузерные push-уведомления действуют на уровне профиля и отправляются на активные браузерные устройства назначенного пользователя.

### Синхронизация календаря

| Способ синхронизации | Подходит для | Документация |
|---|---|---|
| CalDAV | Apple Calendar, Thunderbird, DAVx5 и другие CalDAV-клиенты | [Синхронизация календаря по CalDAV](integrations/caldav.md) |
| Подписной ICS-фид | Outlook, Google Calendar и подписки на веб-календари | [ICS-фид календаря](integrations/ics-calendar-feed.md) |

CalDAV использует персональные API-токены с областью `calendar:read`.
ICS-фиды календаря используют секретные URL подписки и не требуют входа в систему.


## Управление инцидентами

- [Алерты и группы алертов](usage/alerts.md)
- [Приоритеты инцидентов](incidents/priorities.md)
- [Ответственные за инцидент](incidents/responders.md)
- [Заинтересованные стороны инцидента](incidents/stakeholders.md)
- [Комментарии к алертам](usage/alert-comments.md)
- [Заглушки (silences)](usage/silences.md)
- [Окна обслуживания](concepts/maintenance-windows.md)

## Сервисы

  * [Сервисы](concepts/services.md)
  * [Корреляция алертов с учётом зависимостей](concepts/alert-correlation.md)
  * [Заинтересованные стороны сервиса по умолчанию](services/default-stakeholders.md)

## Планирование

- [Календарь](usage/calendar.md)
- [Слои ротации](usage/rotation-layers.md)
- [Переопределения ротации](usage/rotation-overrides.md)
- [Команды, ротации, слои и маршруты](concepts/teams-rotations-routes.md)

## API и автоматизация

Swagger UI:

```text
/docs
```

OpenAPI JSON:

```text
/api/openapi.json
```

Полезные страницы:

- [Обзор API](api/index.md)
- [API сервисов](api/services.md)
- [API политик эскалации](api/escalation-policies.md)
- [API интеграции с Sentry](api/sentry-integration.md)
- [Профиль и личные API-токены](usage/profile-and-tokens.md)
- [Браузерные push-уведомления](usage/browser-push.md)
- [Заметки по OpenAPI для голосовых вызовов](api/voice-call-openapi.md)

## Процесс первичной настройки

```text
1. Install IncidentRelay
2. Configure the service and public_base_url
3. Configure browser push VAPID keys if browser/PWA notifications are required
4. Run migrations
5. Create the first global admin
6. Create a group
7. Create or add users to the group
8. Assign group roles: viewer, editor, user_admin
9. Create a team
10. Add group users to the team
11. Assign team roles: viewer, responder, manager
12. Create a rotation
13. Add rotation members
14. Create a service
15. Add service links and runbooks
16. Create notification channels
17. Ask users to enable browser push in Profile if required
18. Create a route and attach channels
19. Select a default service or configure service match rules
20. Copy the route intake token
21. Configure Alertmanager, Zabbix or webhook sender
22. Send a test alert
23. Acknowledge or resolve the alert
```

Подробнее: [Первый вход и настройка](getting-started/first-login.md).

## Ссылки проекта

- Репозиторий: [https://github.com/roxy-wi/IncidentRelay](https://github.com/roxy-wi/IncidentRelay)
- Swagger UI: `/docs`
- OpenAPI JSON: `/api/openapi.json`
