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

## Запуск без root (с версии 2.3.1)

В Docker-образе права `root` используются **только при инициализации
entrypoint**. После формирования runtime-конфигурации и исправления прав на
томах entrypoint запускает **web, scheduler, Telegram, Slack, миграции и
shell** от пользователя `incidentrelay` (UID/GID `10001`) с помощью `setpriv`.
Для Gunicorn предусмотрен домашний каталог `/home/incidentrelay`.
После запуска UID процесса PID 1 должен равняться `10001`:

```bash
docker compose exec incidentrelay grep ^Uid: /proc/1/status
```

**Важно:** у образа остаётся начальный пользователь root, поэтому обычный
`docker compose exec` по умолчанию тоже может запускать команды от root,
даже если основное приложение уже работает под UID `10001`. Для миграций,
создания пользователей и других административных команд явно указывайте
`--user 10001:10001`, чтобы не создавать новые root-owned файлы.

При первом запуске после обновления установки с **именованными томами Docker
Compose** entrypoint корректирует владельцев в `/var/lib/incidentrelay`
(включая SQLite, WAL и созданный конфиг с правами `0600`) и
`/var/log/incidentrelay`. Уже корректные файлы не меняются, а символические
ссылки за пределы томов не обходятся. Сохранённые секреты остаются прежними.
Для этого однократного исправления entrypoint должен стартовать от root: не
добавляйте `user: "10001:10001"` в Compose, пока тома не подготовлены.

При использовании `docker run --user 12345` или произвольного UID в OpenShift
entrypoint **не меняет владельцев и не повышает привилегии**. Тома, конфиг и
каталоги логов должны быть заранее доступны указанному UID. Если домашний
каталог образа недоступен для записи, переменная `HOME` переключается на
`/tmp`, чтобы Gunicorn не пытался писать в `/`. Внешний конфиг, смонтированный
только для чтения, должен быть читаем пользователем процесса.

Если исправление прав блокируется внешним bind mount, NFS или особенностями
файловой системы, подготовьте права тома средствами администратора хранилища
до обновления. Перед изменением прав сделайте резервную копию SQLite.

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
docker compose exec --user 10001:10001 incidentrelay python manage.py migrate
```

## Создание первого пользователя-администратора

```bash
docker compose exec --user 10001:10001 incidentrelay \
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
