---
title: Настройка
description: Справочник по файлу конфигурации IncidentRelay
---

# Настройка

IncidentRelay читает путь к файлу конфигурации из:

```text
INCIDENTRELAY_CONFIG_FILE
```

Пример:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

Для systemd:

```ini
Environment=INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

Для Docker Compose:

```yaml
environment:
  INCIDENTRELAY_CONFIG_FILE: /etc/incidentrelay/incidentrelay.conf
```

Старое имя `ONCALL_CONFIG_FILE` использовать не следует.

## Основной секрет и секрет аутентификации

Сгенерируйте два разных случайных значения и не меняйте их при перезапусках и
обновлениях:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

```ini
[main]
secret_key = замените-на-первое-случайное-значение

[auth]
jwt_secret = замените-на-второе-случайное-значение
jwt_cookie_secure = true
```

Параметр `secret_key` относится к секции `[main]`, а не `[server]`.
Параметр `jwt_secret` относится к `[auth]`. Не используйте одно значение для
обоих параметров. При HTTPS в `public_base_url` установите
`jwt_cookie_secure = true`.

## Секция server

```ini
[server]
host = 0.0.0.0
port = 8080
public_base_url = https://incidentrelay.example.com
```

| Параметр | Описание |
|---|---|
| `host` | Адрес, к которому привязывается веб-сервис |
| `port` | HTTP-порт |
| `public_base_url` | Внешний URL, используемый в ссылках алертов, кнопках и колбэках |

В продакшене `public_base_url` должен быть реальным внешним HTTPS-URL.

## База данных: SQLite

```ini
[database]
type = sqlite
name = /var/lib/incidentrelay/incidentrelay.db

[sqlite]
wal = true
busy_timeout = 5000
```

SQLite подходит для небольших self-hosted инсталляций. При использовании SQLite оставляйте один веб-воркер.

## База данных: PostgreSQL

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

Используйте PostgreSQL для более крупных инсталляций, высокого объёма алертов, нескольких веб-воркеров или долгосрочных продакшен-развёртываний.


## Политика хранения данных

В IncidentRelay 2.1 все новые retention-настройки находятся в одной секции:

```ini
[retention]
alert_days = 30
# explain_trace_days = 30
# orchestration_execution_days = 30
cleanup_interval_seconds = 86400
batch_size = 500
```

`alert_days = 0` используется по умолчанию и хранит завершённую историю alerts бессрочно. Explain Trace и обычные Event Orchestration executions наследуют `alert_days`, если для них не задан отдельный override. Точные правила удаления и совместимость при обновлении описаны в разделе [Политика хранения данных](../administration/data-retention.md).

## Секция SMTP

Каналы уведомлений по email используют глобальные настройки SMTP. Транспорт SMTP не настраивается отдельно для каждого канала.

```ini
[smtp]
host = 127.0.0.1
port = 25
from = incidentrelay@example.com
use_tls = false
user =
password =
```

Для локального ретранслятора без аутентификации оставьте `user` и `password` пустыми.

Для SMTP-сервера с аутентификацией:

```ini
[smtp]
host = smtp.example.com
port = 587
from = incidentrelay@example.com
use_tls = true
user = incidentrelay@example.com
password = change-me
```

Уведомления по email отправляются на адрес email из профиля назначенного пользователя.

## Прокси для Telegram

Если окружение требует прокси для вызовов Telegram Bot API, настройте его глобально. Значения токенов держите в конфигурации канала, а не в глобальной конфигурации.

Имена параметров в примерах зависят от текущей реализации конфигурации сервиса. Используйте один и тот же файл конфигурации для веб-процессов и процессов Telegram-воркера.

## Секция voice

```ini
[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret = change-me
```

| Параметр | Описание |
|---|---|
| `provider` | Имя голосового провайдера |
| `providers_dir` | Каталог с модулями пользовательских провайдеров |
| `callback_secret` | Секрет, используемый для проверки колбэков |

Уведомления голосовым вызовом отправляются на номер телефона из профиля назначенного пользователя.

## Секция browser push

Браузерные push-уведомления — это уведомления уровня профиля для PWA/браузера. Они не настраиваются как каналы уведомлений.

```ini
[browser_push]
enabled = true
vapid_public_key = CHANGE_ME_PUBLIC_KEY
vapid_private_key = /etc/incidentrelay/vapid/private_key.pem
vapid_subject = mailto:admin@example.com
action_token_ttl_seconds = 900
```

| Параметр | Описание |
|---|---|
| `enabled` | Включает или отключает браузерные push-уведомления глобально |
| `vapid_public_key` | Публичный ключ VAPID, возвращаемый браузеру для `PushManager.subscribe()` |
| `vapid_private_key` | Приватный ключ VAPID или путь к PEM-файлу, используемый сервером для отправки сообщений Web Push |
| `vapid_subject` | Контактный URI, включаемый в claims VAPID, обычно `mailto:admin@example.com` |
| `action_token_ttl_seconds` | Время жизни одноразовых токенов ACK/Resolve, встраиваемых в push-уведомления |

После изменения настроек браузерных push-уведомлений перезапустите веб-сервис. Перезапустите также планировщик, если в вашей инсталляции он отправляет уведомления.

Подробнее: [Браузерные push-уведомления](../usage/browser-push.md).

## Настройки планировщика

Процесс планировщика проверяет напоминания, эскалации и периодические задания.

Интервал пробуждения планировщика отличается от интервалов напоминаний ротаций. Интервалы напоминаний ротаций настраиваются для каждой ротации отдельно:

```text
0 disables reminders for that rotation
>= 60 sends reminders at that interval in seconds
1..59 invalid
```

Не используйте глобальную настройку reminder-after как запасной вариант во время выполнения, когда ротации требуют явного интервала.

## Журналирование

Если включено журналирование в файл, используйте путь с правами на запись:

```ini
[main]
log_level = INFO
log_file = /var/log/incidentrelay/incidentrelay.log
```

Для systemd и контейнеров проверяйте также журнал или логи контейнера.
