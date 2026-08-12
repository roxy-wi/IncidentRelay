---
title: README проекта IncidentRelay
description: Обзор репозитория, рабочий процесс, установка и сводка по API.
---

# IncidentRelay

IncidentRelay — это self-hosted сервис для планирования дежурств (on-call), маршрутизации алертов и уведомлений.

Он предоставляет:

- группы и RBAC;
- команды и ротации;
- каталог сервисов с затронутыми системами, ссылками, runbook’ами, зависимостями и аналитикой влияния;
- токены приёма алертов на основе маршрутов;
- приём из Alertmanager, Zabbix и обобщённых вебхуков;
- каналы уведомлений Mattermost, Telegram, email, на основе вебхуков и голосовых вызовов;
- рабочие процессы ACK и Resolve;
- напоминания и эскалацию;
- заглушки (silences) и переопределения ротаций;
- представление календаря;
- персональные API-токены;
- документацию Swagger/OpenAPI.

## Основной рабочий процесс

```text
Monitoring system -> Route -> Service -> Team -> Rotation -> Notification channels -> ACK / Resolve
```

Маршруты определяют, как алерты попадают в IncidentRelay. Сервисы описывают, какая логическая система затронута.

Порядок отображения сервиса и команды:

```text
name -> slug -> "-"
```

## Установка

Выберите один способ:

| Способ | Документация |
|---|---|
| Docker Compose | [Установка через Docker](getting-started/docker.md) |
| RPM package | [Установка через RPM](getting-started/rpm-installation.md) |
| Manual systemd | [Ручная установка через systemd](getting-started/systemd.md) |

## Сервисы времени выполнения

IncidentRelay следует запускать как отдельные сервисы:

```text
incidentrelay           # web API, UI, incoming webhooks
incidentrelay-scheduler # reminders, escalations, periodic jobs
```

Telegram-воркер опционален и нужен только тогда, когда используются опрос (polling) или действия Telegram.

## Настройка

IncidentRelay читает путь к конфигурации из:

```text
INCIDENTRELAY_CONFIG_FILE
```

Пример:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

Не используйте старое имя `ONCALL_CONFIG_FILE`.

## Миграции базы данных

```bash
python manage.py migrate
```

## Создание первого администратора

```bash
python manage.py create-admin   --username admin   --password 'change-me-123'   --email admin@example.com
```

## Процесс первичной настройки

```text
1. Create a group
2. Create users
3. Add users to the group
4. Create a team
5. Add users to the team
6. Create a rotation
7. Add rotation members
8. Create a service
9. Add service links and runbooks
10. Create notification channels
11. Create a route and select default service
12. Copy the route intake token
13. Configure Alertmanager, Zabbix, or webhook sender
14. Send a test alert
15. Acknowledge or resolve the alert
```

## Сервисы

Сервис описывает затронутую систему, например:

```text
RabbitMQ Cloud
Billing API
PostgreSQL Prod
Frontend Web
```

Сервис может иметь:

- ссылки на дашборд, логи, трейсы, репозиторий и документацию;
- обобщённые runbook’и;
- специфичные для алертов runbook’и, выбираемые матчерами;
- зависимости;
- аналитику и статус влияния.

Поведение матчера runbook’ов:

```text
empty matchers -> generic runbook for all alerts of the service
matchers set   -> runbook only for matching alerts
```

## Уведомления по email

Канал email не хранит получателей или настройки SMTP-транспорта.

- SMTP настраивается глобально в файле конфигурации.
- Письма отправляются на адрес email из профиля назначенного пользователя.
- Канал email может при необходимости переопределить HTML-шаблон.

## Интервалы напоминаний

Интервал напоминаний настраивается на ротациях:

```text
0 disables reminders
>= 60 enables reminders
1..59 invalid
```

## API

Swagger UI:

```text
/docs
```

OpenAPI JSON:

```text
/api/openapi.json
```

Эндпоинты Service API доступны по адресу:

```text
/api/services
```

## Документация

| Тема | Ссылка |
|---|---|
| Первый вход | [getting-started/first-login.md](getting-started/first-login.md) |
| Сервисы | [concepts/services.md](concepts/services.md) |
| Алерты | [usage/alerts.md](usage/alerts.md) |
| Токены приёма маршрутов | [concepts/route-intake-tokens.md](concepts/route-intake-tokens.md) |
| API | [api/index.md](api/index.md) |
| Устранение неполадок | [administration/troubleshooting.md](administration/troubleshooting.md) |

## Лицензия

MIT
