---
title: Установка через RPM
description: Установка и проверка IncidentRelay на RedHat-подобных дистрибутивах из RPM-репозитория
---

# Установка через RPM

Используйте это руководство для инсталляций на RHEL, Rocky Linux, AlmaLinux и CentOS Stream.

!!! warning
    Успешная команда `dnf install` означает только то, что файлы RPM распакованы.
    Не публикуйте сервис, пока не пройдут проверки Python, конфигурации,
    миграций и readiness из этого руководства.

Файл репозитория:

```text
https://repo.incidentrelay.io/incidentrelay.repo
```

## 1. Установка файла репозитория

Для систем на основе DNF:

```bash
sudo dnf install -y curl openssl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo dnf makecache
```

Для более старых систем на основе yum:

```bash
sudo yum install -y curl openssl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo yum makecache
```

## 2. Установка IncidentRelay

```bash
sudo dnf install -y incidentrelay
```

Или с помощью `yum`:

```bash
sudo yum install -y incidentrelay
```

RPM-пакет устанавливает приложение и файлы сервисов, используя следующие пути:

```text
/var/www/incidentrelay                    # application directory
/etc/incidentrelay/incidentrelay.conf     # main configuration file
/var/lib/incidentrelay                    # runtime data, SQLite database by default
/var/log/incidentrelay                    # application logs
/usr/local/lib/incidentrelay/voice_providers # custom voice providers
```

Пакет должен работать под выделенным системным пользователем:

```text
incidentrelay
```

## 3. Проверка Python-runtime из пакета

IncidentRelay требует Python 3.10 или новее. В EL9 команда `/usr/bin/python3`
запускает Python 3.9, поэтому веб-сервис и планировщик должны использовать venv
из пакета, а не системный интерпретатор.

```bash
rpm -q incidentrelay
sudo test -x /var/www/incidentrelay/venv/bin/python
/var/www/incidentrelay/venv/bin/python --version
/var/www/incidentrelay/venv/bin/python -c \
  'import flask, peewee, gunicorn, joserfc; print("Python dependencies: OK")'
```

Команда версии должна показать Python 3.10 или новее, а проверка импортов должна
завершиться без исключения.

### Восстановление неполного runtime RPM 2.0-1 в EL9

Некоторые сборки `incidentrelay-2.0-1` устанавливают код, но оставляют сервисы
на Python 3.9 или не устанавливают часть зависимостей. Сохраните окружение из
пакета, создайте venv Python 3.11 и установите зависимости:

```bash
sudo dnf install -y python3.11 python3.11-pip
if sudo test -e /var/www/incidentrelay/venv; then
  sudo mv /var/www/incidentrelay/venv \
    "/var/www/incidentrelay/venv.rpm-backup.$(date +%Y%m%d%H%M%S)"
fi
sudo /usr/bin/python3.11 -m venv /var/www/incidentrelay/venv
sudo /var/www/incidentrelay/venv/bin/python -m pip install --upgrade pip
sudo /var/www/incidentrelay/venv/bin/python -m pip install \
  -r /var/www/incidentrelay/requirements.txt \
  gunicorn joserfc
sudo chown -R root:incidentrelay /var/www/incidentrelay/venv
sudo chmod -R g+rX,o-rwx /var/www/incidentrelay/venv
```

Если версия зависимости из requirements RPM отсутствует, установите исправленную
сборку пакета. Проверенные как временное восстановление для 2.0-1 версии:
`regex==2026.1.15`, `pyTelegramBotAPI==4.32.0` и `Authlib==1.6.12`.

После восстановления venv повторите проверку импортов.

## 4. Настройка IncidentRelay

Отредактируйте:

```bash
sudo vi /etc/incidentrelay/incidentrelay.conf
```

Сгенерируйте два разных секрета командой `openssl rand -hex 32`, затем проверьте
как минимум:

```ini
[main]
secret_key = замените-на-первое-случайное-значение
timezone = UTC

[server]
public_base_url = https://incidentrelay.example.com

[database]
type = sqlite
name = /var/lib/incidentrelay/incidentrelay.db

[auth]
jwt_secret = замените-на-второе-случайное-значение
jwt_cookie_secure = true
```

`secret_key` относится к `[main]`, а не к `[server]`. Для файла SQLite
используется `name`, а не `path`. Значения `secret_key` и `jwt_secret` должны
быть непустыми, разными и постоянными. Укажите реальное DNS-имя или публичный IP
в `public_base_url`; для HTTPS установите `jwt_cookie_secure = true`.

Для PostgreSQL используйте:

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

В примере конфигурации 2.0-1 могут повторяться параметры
`alert_group_window_seconds` и `callback_secret`. Оставьте каждый параметр один
раз и проверьте весь файл:

```bash
sudo -u incidentrelay \
  /var/www/incidentrelay/venv/bin/python -c \
  'from configparser import ConfigParser; p="/etc/incidentrelay/incidentrelay.conf"; c=ConfigParser(interpolation=None, strict=True); c.read(p); print("Configuration: OK")'
```

Закройте права на конфигурацию и разрешите сервису запись в runtime-каталоги:

```bash
sudo chown root:incidentrelay /etc/incidentrelay/incidentrelay.conf
sudo chmod 0640 /etc/incidentrelay/incidentrelay.conf
sudo chown -R incidentrelay:incidentrelay \
  /var/lib/incidentrelay /var/log/incidentrelay
sudo chmod 0750 /var/lib/incidentrelay /var/log/incidentrelay
```

## 5. Перевод обоих systemd-сервисов на venv

Посмотрите итоговые unit-файлы:

```bash
sudo systemctl cat incidentrelay
sudo systemctl cat incidentrelay-scheduler
```

Если unit использует `/usr/bin/python3` или глобальный `gunicorn`, добавьте
systemd drop-in. Для SQLite оставьте один веб-воркер:

```bash
sudo systemctl edit incidentrelay
```

```ini
[Service]
ExecStart=
ExecStart=/var/www/incidentrelay/venv/bin/python -m gunicorn --workers 1 --threads 4 --timeout 120 --bind 127.0.0.1:8080 --access-logfile /var/log/incidentrelay/gun-incidentrelay.log --error-logfile /var/log/incidentrelay/gun-incidentrelay_error.log --capture-output app:create_app()
UMask=0027
```

```bash
sudo systemctl edit incidentrelay-scheduler
```

```ini
[Service]
ExecStart=
ExecStart=/var/www/incidentrelay/venv/bin/python -m app.scheduler_worker
UMask=0027
```

Примените изменения:

```bash
sudo systemctl daemon-reload
```

## 6. Миграции и проверка схемы

RPM-пакет может запускать миграции во время установки. Если база данных не была готова во время установки, запустите миграции вручную после редактирования конфигурации:

```bash
cd /var/www/incidentrelay
sudo -u incidentrelay env \
  PYTHONPATH=/var/www/incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python manage.py migrate

sudo -u incidentrelay env \
  PYTHONPATH=/var/www/incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python -m app.check_schema
```

Обе команды должны завершиться с кодом 0.

## 7. Создание первого пользователя-администратора

```bash
cd /var/www/incidentrelay
sudo -u incidentrelay env \
  PYTHONPATH=/var/www/incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

Смените пароль и email перед использованием в продакшене.

## 8. Запуск и проверка сервисов

Включите и запустите веб-сервис и планировщик:

```bash
sudo systemctl enable --now incidentrelay
sudo systemctl enable --now incidentrelay-scheduler
```

Проверьте статус сервисов:

```bash
sudo systemctl status incidentrelay
sudo systemctl status incidentrelay-scheduler
curl -fsS http://127.0.0.1:8080/readyz
```

Следите за логами:

```bash
sudo journalctl -u incidentrelay -f
sudo journalctl -u incidentrelay-scheduler -f
```

Веб-сервис из пакета слушает `127.0.0.1:8080`. Не открывайте порт 8080 в
Интернет. Используйте Nginx или другой reverse proxy на портах 80 и 443 и
настройте TLS. В системах с SELinux разрешите Nginx подключаться к локальному
upstream:

```bash
sudo setsebool -P httpd_can_network_connect 1
```

После настройки proxy проверьте с другой машины и откройте:

```text
https://YOUR_PUBLIC_NAME_OR_IP/readyz
https://YOUR_PUBLIC_NAME_OR_IP/login
```

Для публичного IP можно использовать IP-сертификат Let's Encrypt с Certbot 5.4
или новее и профилем `shortlived`. Такой сертификат действует около шести дней,
поэтому автоматическое продление обязательно. См.
[инструкцию Let's Encrypt](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/).

## 9. Опциональный Telegram-воркер

Запускайте этот сервис, только если используется polling Telegram или обработка колбэков:

```bash
sudo systemctl enable --now incidentrelay-telegram-worker
```

Проверьте логи:

```bash
sudo journalctl -u incidentrelay-telegram-worker -f
```

## 10. Обновление IncidentRelay

!!! warning "Обновление с 1.2 на 2.1 или новее"
    IncidentRelay 2.1 блокирует private/loopback/link-local/reserved адреса
    исходящих HTTP-запросов, если они не разрешены явно. Поэтому существующие
    внутренние OIDC metadata/JWKS endpoints и исходящие webhook/API-интеграции
    могут перестать работать сразу после обновления.

До обновления определите внутренние endpoints, к которым обращается
IncidentRelay, и добавьте минимально необходимые CIDR/IP в текущую конфигурацию:

```ini
[security]
outbound_private_network_allowlist = 10.20.0.0/16,192.168.50.10/32
```

RPM устанавливает `incidentrelay.conf` как конфигурацию `noreplace`, поэтому
существующий файл сохраняется при обновлении. Проверьте наличие
`/etc/incidentrelay/incidentrelay.conf.rpmnew`, но не рассчитывайте, что новый
security-параметр автоматически попадёт в активный конфиг. Подробности о DNS и
дополнительные примеры см. в разделе
[Политика исходящих HTTP-подключений](configuration.md#политика-исходящих-http-подключений).

```bash
sudo dnf update -y incidentrelay
```

Или с помощью `yum`:

```bash
sudo yum update -y incidentrelay
```

После обновления запустите миграции при необходимости:

```bash
cd /var/www/incidentrelay
sudo -u incidentrelay env \
  PYTHONPATH=/var/www/incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python manage.py migrate
```

Затем перезапустите сервисы:

```bash
sudo systemctl restart incidentrelay
sudo systemctl restart incidentrelay-scheduler
```

Если используется Telegram-воркер:

```bash
sudo systemctl restart incidentrelay-telegram-worker
```

## 11. Удаление IncidentRelay

```bash
sudo dnf remove -y incidentrelay
```

Или с помощью `yum`:

```bash
sudo yum remove -y incidentrelay
```

Конфигурация и runtime-данные могут остаться на диске в зависимости от политики удаления пакета. Удаляйте их вручную только когда вы уверены, что данные больше не нужны:

```bash
sudo rm -rf /etc/incidentrelay
sudo rm -rf /var/lib/incidentrelay
sudo rm -rf /var/log/incidentrelay
```
