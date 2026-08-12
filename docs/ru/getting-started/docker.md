---
title: Установка через Docker
description: Запуск IncidentRelay с помощью Docker Compose
---

# Установка через Docker

Docker Compose — самый быстрый способ запустить IncidentRelay для тестирования, демонстраций и простых self-hosted развёртываний.

Стандартная конфигурация Compose запускает:

```text
incidentrelay             # HTTP API, UI, incoming webhooks
incidentrelay-scheduler   # reminders, escalations, periodic jobs
```

PostgreSQL опционален. SQLite подходит для небольших инсталляций и быстрого старта.

## Архитектура по умолчанию

```text
Docker Compose
├── incidentrelay
│   └── Gunicorn + Flask application
├── incidentrelay-scheduler
│   └── standalone scheduler worker
└── incidentrelay-data
    └── SQLite database volume
```

Путь к SQLite по умолчанию внутри контейнера:

```text
/var/lib/incidentrelay/incidentrelay.db
```

Путь к конфигурации по умолчанию внутри контейнера:

```text
/etc/incidentrelay/incidentrelay.conf
```

Файл конфигурации выбирается через:

```text
INCIDENTRELAY_CONFIG_FILE
```

## Быстрый старт с SQLite

```bash
docker compose up -d --build
```

Откройте UI:

```text
http://SERVER_IP:8080/login
```

Показать логи:

```bash
docker compose logs -f incidentrelay
docker compose logs -f incidentrelay-scheduler
```

## Запуск миграций

Если миграции не запускаются автоматически точкой входа вашего контейнера, выполните:

```bash
docker compose exec incidentrelay python manage.py migrate
```

## Создание первого пользователя-администратора

```bash
docker compose exec incidentrelay \
  python manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

Смените пароль и email перед использованием в продакшене.

## Конфигурация SQLite по умолчанию

Файл:

```text
docker/incidentrelay.docker.conf
```

Пример:

```ini
[main]
log_level = INFO
log_file = /var/log/incidentrelay/incidentrelay.log

[server]
host = 0.0.0.0
port = 8080
public_base_url = http://localhost:8080

[database]
type = sqlite
path = /var/lib/incidentrelay/incidentrelay.db

[sqlite]
wal = true
busy_timeout = 5000

[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret = change-me
```

## Вариант с PostgreSQL

Используйте PostgreSQL для:

- более крупных команд;
- высокого объёма алертов;
- нескольких веб-воркеров;
- долгосрочных продакшен-инсталляций.

Запускайте с PostgreSQL, если репозиторий предоставляет override для Compose с PostgreSQL:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.postgres.yml \
  up -d
```

Пример конфигурации PostgreSQL:

```ini
[database]
type = postgresql
host = postgres
port = 5432
name = incidentrelay
user = incidentrelay
password = incidentrelay-change-me
```

## Внешний доступ

При таком отображении портов:

```yaml
ports:
  - "8080:8080"
```

IncidentRelay доступен по адресу:

```text
http://SERVER_IP:8080
```

если файрвол разрешает порт `8080`.

Для продакшена лучше публиковать IncidentRelay через Nginx или HAProxy с HTTPS:

```text
Internet -> Nginx/HAProxy :443 -> IncidentRelay :8080
```

Правильно задайте публичный URL:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

`public_base_url` используется для генерируемых ссылок и колбэков.

## Пользовательские голосовые провайдеры

Пользовательские голосовые провайдеры можно смонтировать в:

```text
/usr/local/lib/incidentrelay/voice_providers
```

Пример монтирования в Compose:

```yaml
volumes:
  - ./custom_voice_providers:/usr/local/lib/incidentrelay/voice_providers:ro
```

После изменения файлов провайдеров перезапустите контейнеры:

```bash
docker compose restart incidentrelay incidentrelay-scheduler
```
