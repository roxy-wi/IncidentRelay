---
title: Установка с systemd
description: Быстрая установка с сервисами systemd
---

# Установка с systemd

Это руководство описывает классическую установку в Linux с systemd.

Оно запускает два сервиса:

```text
incidentrelay.service        # HTTP API, UI, webhooks
incidentrelay-scheduler.service  # reminders, escalations, periodic jobs
```

Планировщик должен работать как отдельный сервис. Не запускайте его внутри каждого веб-воркера.

## Рекомендуемые пути

```text
/var/www/incidentrelay                     # application directory
/var/www/incidentrelay/venv                # Python virtual environment
/etc/incidentrelay/incidentrelay.conf      # configuration file
/var/lib/incidentrelay                     # SQLite database or runtime state
/var/log/incidentrelay                     # logs
/usr/local/lib/incidentrelay/voice_providers # custom voice providers
```

IncidentRelay читает путь к конфигурации из:

```text
INCIDENTRELAY_CONFIG_FILE
```

Старую переменную `ONCALL_CONFIG_FILE` использовать не следует.

## 1. Установка системных пакетов

Пример для Debian / Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y \
  git \
  python3 \
  python3-venv \
  python3-pip \
  build-essential \
  curl
```

Если вы используете PostgreSQL, установите также сборочные/runtime-зависимости PostgreSQL:

```bash
sudo apt-get install -y libpq-dev
```

## 2. Клонирование IncidentRelay

```bash
sudo mkdir -p /var/www
sudo git clone https://github.com/roxy-wi/IncidentRelay.git /var/www/incidentrelay
cd /var/www/incidentrelay
```

## 3. Создание виртуального окружения

```bash
sudo python3 -m venv /var/www/incidentrelay/venv
sudo /var/www/incidentrelay/venv/bin/pip install --upgrade pip
sudo /var/www/incidentrelay/venv/bin/pip install -r /var/www/incidentrelay/requirements.txt
sudo /var/www/incidentrelay/venv/bin/pip install gunicorn
```

Для инсталляций с PostgreSQL:

```bash
sudo /var/www/incidentrelay/venv/bin/pip install psycopg2-binary
```

## 4. Создание каталогов

```bash
sudo mkdir -p /etc/incidentrelay
sudo mkdir -p /var/lib/incidentrelay
sudo mkdir -p /var/log/incidentrelay
sudo mkdir -p /usr/local/lib/incidentrelay/voice_providers
```

Установите владельца:

```bash
sudo chown -R www-data:www-data /var/www/incidentrelay
sudo chown -R www-data:www-data /var/lib/incidentrelay
sudo chown -R www-data:www-data /var/log/incidentrelay
```

Файлы пользовательских голосовых провайдеров — это исполняемый код Python. Держите этот каталог доступным для записи только администраторам:

```bash
sudo chown root:root /usr/local/lib/incidentrelay/voice_providers
sudo chmod 755 /usr/local/lib/incidentrelay/voice_providers
```

## 5. Создание конфигурации

Создайте:

```text
/etc/incidentrelay/incidentrelay.conf
```

Пример для SQLite:

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

Для продакшена за Nginx или HAProxy задайте `public_base_url` равным реальному внешнему URL:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

`public_base_url` используется для генерируемых ссылок и URL колбэков.

## 6. Установка сервисов systemd

Скопируйте файлы сервисов:

```bash
sudo cp /var/www/incidentrelay/systemd/incidentrelay.service /etc/systemd/system/
sudo cp /var/www/incidentrelay/systemd/incidentrelay-scheduler.service /etc/systemd/system/
```

Перезагрузите systemd:

```bash
sudo systemctl daemon-reload
```

## 7. Запуск миграций

```bash
cd /var/www/incidentrelay
sudo -u www-data \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python app/migrate.py migrate
```

## 8. Создание первого пользователя-администратора

```bash
cd /var/www/incidentrelay
sudo -u www-data \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

## 9. Запуск сервисов

```bash
sudo systemctl enable incidentrelay
sudo systemctl enable incidentrelay-scheduler

sudo systemctl start incidentrelay
sudo systemctl start incidentrelay-scheduler
```

Проверьте статус:

```bash
sudo systemctl status incidentrelay
sudo systemctl status incidentrelay-scheduler
```

Откройте:

```text
http://SERVER_IP:8080/login
```

## 10. Логи

Логи веб-сервиса:

```bash
journalctl -u incidentrelay -f
```

Логи планировщика:

```bash
journalctl -u incidentrelay-scheduler -f
```

Файл лога приложения:

```bash
tail -f /var/log/incidentrelay/incidentrelay.log
```

## Файлы сервисов systemd

### Веб-сервис

```ini
[Unit]
Description=IncidentRelay Web service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

User=www-data
Group=www-data

WorkingDirectory=/var/www/incidentrelay

Environment=INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
Environment=INCIDENTRELAY_SERVICE=web
Environment=PYTHONUNBUFFERED=1

ExecStart=/var/www/incidentrelay/venv/bin/gunicorn \
  --bind 0.0.0.0:8080 \
  --workers 1 \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"

Restart=always
RestartSec=5

KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

### Сервис планировщика

```ini
[Unit]
Description=IncidentRelay Scheduler service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

User=www-data
Group=www-data

WorkingDirectory=/var/www/incidentrelay

Environment=INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
Environment=INCIDENTRELAY_SERVICE=scheduler
Environment=PYTHONUNBUFFERED=1

ExecStart=/var/www/incidentrelay/venv/bin/python -m app.scheduler_worker

Restart=always
RestartSec=5

KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

## Важное замечание о планировщике

Веб-процесс не должен запускать планировщик автоматически.

Правильная модель:

```text
web service:
  create_app()
  no scheduler autostart

scheduler service:
  create_app()
  start_scheduler()
```

Если запуск планировщика сейчас происходит внутри `create_app()`, защитите его условием:

```python
import os

if os.getenv("INCIDENTRELAY_SERVICE") == "scheduler":
    start_scheduler()
```

Если `app.scheduler_worker` запускает планировщик явно, обычно лучше полностью убрать автоматический запуск планировщика из `create_app()`.

## Продакшен с обратным прокси

Для продакшена обычно лучше привязать Gunicorn к localhost и публиковать IncidentRelay через Nginx или HAProxy с HTTPS.

Измените `ExecStart` веб-сервиса:

```ini
ExecStart=/var/www/incidentrelay/venv/bin/gunicorn \
  --bind 127.0.0.1:8080 \
  --workers 1 \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
```

Затем задайте:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

## Вариант с PostgreSQL

Для более крупных инсталляций используйте PostgreSQL.

Пример секции конфигурации:

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

Для PostgreSQL при необходимости увеличьте число веб-воркеров:

```ini
ExecStart=/var/www/incidentrelay/venv/bin/gunicorn \
  --bind 127.0.0.1:8080 \
  --workers 4 \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
```

Для SQLite оставляйте `--workers 1`.

## Обновление IncidentRelay

```bash
cd /var/www/incidentrelay
sudo systemctl stop incidentrelay-scheduler
sudo systemctl stop incidentrelay

sudo git pull
sudo /var/www/incidentrelay/venv/bin/pip install -r requirements.txt

sudo -u www-data \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python app/migrate.py migrate

sudo systemctl start incidentrelay
sudo systemctl start incidentrelay-scheduler
```

## Устранение неполадок

### Файл конфигурации не найден

Проверьте:

```bash
systemctl show incidentrelay --property=Environment
systemctl show incidentrelay-scheduler --property=Environment
```

Проверьте, что файл существует:

```bash
ls -l /etc/incidentrelay/incidentrelay.conf
```

### Отказ в доступе к базе данных SQLite

Проверьте права доступа:

```bash
sudo -u www-data test -w /var/lib/incidentrelay
sudo -u www-data test -r /etc/incidentrelay/incidentrelay.conf
```

### Напоминания дублируются

Проверьте, что планировщик не запущен внутри веб-воркеров и что активен только один сервис планировщика:

```bash
systemctl status incidentrelay-scheduler
ps aux | grep scheduler
```

### Сервис не запускается после обновления кода

Проверьте логи:

```bash
journalctl -u incidentrelay -n 100 --no-pager
journalctl -u incidentrelay-scheduler -n 100 --no-pager
```
