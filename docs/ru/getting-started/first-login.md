---
title: Первый вход и настройка
description: Первоначальная настройка в веб-интерфейсе IncidentRelay
---

# Первый вход и настройка

Откройте:

```text
/login
```

Войдите под пользователем-администратором, созданным командой `manage.py create-admin`.

## Шаг 1. Создание группы

Откройте:

```text
Administration -> Groups
```

Создайте группу:

```text
Slug: production
Name: Production
```

## Шаг 2. Создание пользователей

Откройте:

```text
Administration -> Users
```

Создайте пользователей:

```text
ivan
petr
sergey
```

### Альтернатива: синхронизация администраторов из usergroup Slack

Вместо создания пользователей вручную вы можете импортировать их из usergroup Slack с помощью команды управления `sync-slack-admins`.

Команде требуется bot-токен со следующими scope: `usergroups:read`, `users:read`, `users:read.email`.

Запустите один раз, чтобы завести всех участников группы как администраторов:

```bash
python manage.py sync-slack-admins --usergroup admins
```

Или передайте токен явно:

```bash
python manage.py sync-slack-admins \
  --slack-token xoxb-... \
  --usergroup admins
```

Аргумент `--usergroup` принимает handle usergroup Slack (`admins`, `@admins`) или сырой ID группы (`S0123ABCDE`).

Для вновь созданных пользователей генерируется случайный пароль, который выводится в JSON-выводе. Чтобы вместо этого задать фиксированный пароль:

```bash
python manage.py sync-slack-admins --usergroup admins --password changeme
```

Для каждого участника команда:

- создаёт пользователя, если он не найден (сопоставление по `slack_user_id` или производному username);
- обновляет `email`, `display_name`, `slack_user_id`, `is_admin=True` для существующих пользователей;
- пропускает боты и удалённые аккаунты Slack.

Повторный запуск команды безопасен — существующие пользователи обновляются, а не дублируются.

## Шаг 3. Добавление пользователей в группу

Откройте:

```text
Administration -> Groups
```

Используйте `Add user to group`.

Пример:

```text
Group: Production
User: ivan
Role: rw
```

Повторите для всех пользователей. Участников группы можно посмотреть на той же странице, нажав `Members` рядом с группой.

## Шаг 4. Создание команды

Откройте:

```text
Teams
```

Создайте команду:

```text
Group: Production
Slug: infra
Name: Infrastructure
Escalate after reminders: 2
```

`Escalate after reminders` означает, сколько сообщений-напоминаний отправляется до того, как алерт будет назначен следующему дежурному пользователю.

## Шаг 5. Добавление пользователей в команду

Откройте:

```text
Teams
```

Нажмите `Members` рядом с командой. Используйте `Add user to selected team`.

Пример:

```text
User: ivan
Role: rw
```

Повторите для всех пользователей, которые должны участвовать в расписании команды.

## Шаг 6. Создание ротации

Откройте:

```text
Rotations
```

Создайте ротацию:

```text
Team: infra
Name: infra-primary
Type: daily
Handoff time: 09:00
Timezone: UTC or your team timezone
Reminder interval: 300 seconds
```

Ротация — это календарный объект, используемый маршрутами, сервисами и алертами. При создании ротации IncidentRelay создаёт внутри неё `Default layer`.

Если включена опция `Add all active team members to this rotation`, все активные участники команды добавляются в слой по умолчанию в порядке команды.

## Шаг 7. Настройка слоёв ротации

Откройте:

```text
Rotations -> Layers
```

Слой определяет, кто дежурит, когда происходит передача дежурства и когда слой активен.

Для простого расписания 24/7 оставьте слой по умолчанию и добавьте пользователей:

```text
Position 0: ivan
Position 1: petr
Position 2: sergey
```

Для рабочих часов, ночей и выходных создайте отдельные слои:

```text
Layer: Business hours
Priority: 10
Active: Monday-Friday 09:00-18:00

Layer: Nights
Priority: 20
Active: Monday-Friday 18:00-09:00

Layer: Weekend
Priority: 30
Active: Saturday-Sunday 00:00-00:00
```

Активные слои с более высоким приоритетом переопределяют активные слои с более низким приоритетом.

Если у слоя нет ограничений, он активен 24/7.

## Шаг 8. Проверка календаря

Откройте:

```text
Calendar
```

Убедитесь, что итоговое расписание выглядит корректно. Календарь отображает по одному календарю ротации за раз. Если у команды несколько ротаций, выберите нужную ротацию.

Календарь использует итоговое расписание:

```text
override > highest-priority active layer > no assignment
```

## Шаг 9. Создание сервиса

Откройте:

```text
Services
```

Создайте сервис:

```text
Team: infra
Slug: rabbitmq-cloud
Name: RabbitMQ Cloud
Type: queue
Environment: production
Criticality: critical
Tier: tier_1
Status: operational
```

Сервис описывает затронутую систему. Маршруты принимают алерты, а сервисы объясняют, какая система сломана.

Опциональный, но рекомендуемый контекст сервиса:

```text
Dashboard link: https://grafana.example.com/d/rabbitmq-cloud
Logs link: https://logs.example.com/rabbitmq-cloud
Runbook: https://docs.example.com/runbooks/rabbitmq
```

Ссылки сервиса — это стабильные URL для всего сервиса. Runbook'и могут быть общими для всего сервиса или сопоставленными с конкретным алертом.

Порядок отображения в UI и уведомлениях:

```text
name -> slug -> "-"
```

## Шаг 10. Создание канала уведомлений

Откройте:

```text
Channels
```

Выберите:

```text
Group: Production
Team: infra
```

Создайте канал, например, в режиме Mattermost Bot API:

```text
Type: mattermost
Mode: Bot API with buttons and message updates
Mattermost URL: https://mattermost.example.com
Bot token:
Channel ID:
Callback secret: optional
```

У каналов нет токенов приёма алертов. Они только определяют, куда отправляются уведомления.

### Опционально: включение браузерных push-уведомлений для ответственных

Браузерные push-уведомления — это не канал. Они включаются каждым пользователем в разделе Profile и доставляются на браузер/PWA-устройства этого пользователя, когда ему назначается алерт.

Откройте:

```text
Profile
```

Используйте `Enable push on this device`, разрешите уведомления браузера, затем используйте `Send test push`.

Подробнее: [Браузерные push-уведомления](../usage/browser-push.md).

## Шаг 11. Создание маршрута

Откройте:

```text
Routes
```

Создайте маршрут:

```text
Team: infra
Source: alertmanager
Rotation: infra-primary
Default service: RabbitMQ Cloud
Channels: infra-mattermost
Matchers JSON: {"labels": {"team": "infra"}}
Group by JSON: ["alertname", "instance"]
```

Скопируйте токен приёма маршрута после создания маршрута. Если токен маршрута потерян, откройте Routes и нажмите `Regenerate token` рядом с маршрутом.

Используйте `Default service`, когда все алерты, попадающие в маршрут, относятся к одной логической системе.

Если один маршрут принимает алерты для нескольких систем, создайте правила сопоставления сервисов.

Пример правила сопоставления сервиса RabbitMQ:

```json
{
  "labels": {
    "job": "RabbitMQ",
    "rabbitmq": {
      "op": "regex",
      "value": "^rabbitmq-cloud$"
    }
  }
}
```

## Шаг 12. Отправка тестового алерта

Пример запроса Alertmanager:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/alertmanager \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ALERTMANAGER_ROUTE_TOKEN' \
  -d '{
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "RabbitMQClusterPartition",
          "severity": "critical",
          "team": "infra",
          "job": "RabbitMQ",
          "rabbitmq": "rabbitmq-cloud",
          "instance": "rabbit-1"
        },
        "annotations": {
          "summary": "RabbitMQ cluster partition detected",
          "description": "Erlang distribution link is not healthy"
        },
        "fingerprint": "rabbitmq-cloud-partition-rabbit-1"
      }
    ]
  }'
```

Откройте `Alerts` и убедитесь, что алерт был направлен в ожидаемую команду, сервис и назначен ожидаемому дежурному пользователю.

## Шаг 13. Подтверждение или разрешение алерта

Откройте:

```text
Alerts
```

Используйте:

```text
Acknowledge
Resolve
```

Когда алерт привязан к сервису, детали алерта и уведомления могут включать ссылки сервиса и соответствующие runbook'и.
