---
title: Установка через RPM
description: Установка IncidentRelay на дистрибутивах семейства RedHat из RPM-репозитория
---

# Установка через RPM

Используйте это руководство для инсталляций на RHEL, Rocky Linux, AlmaLinux и CentOS Stream.

Файл репозитория:

```text
https://repo.incidentrelay.io/incidentrelay.repo
```

## 1. Установка файла репозитория

Для систем на основе DNF:

```bash
sudo dnf install -y curl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo dnf makecache
```

Для более старых систем на основе yum:

```bash
sudo yum install -y curl
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

## 3. Настройка IncidentRelay

Отредактируйте:

```bash
sudo vi /etc/incidentrelay/incidentrelay.conf
```

Как минимум, проверьте:

```ini
[server]
secret_key = change-me
public_base_url = https://incidentrelay.example.com

[database]
type = sqlite
path = /var/lib/incidentrelay/incidentrelay.db
```

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

## 4. Запуск миграций базы данных

RPM-пакет может запускать миграции во время установки. Если база данных не была готова во время установки, запустите миграции вручную после редактирования конфигурации:

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py migrate
```

## 5. Создание первого пользователя-администратора

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

Смените пароль и email перед использованием в продакшене.

## 6. Запуск сервисов

Включите и запустите веб-сервис и планировщик:

```bash
sudo systemctl enable --now incidentrelay
sudo systemctl enable --now incidentrelay-scheduler
```

Проверьте статус сервисов:

```bash
sudo systemctl status incidentrelay
sudo systemctl status incidentrelay-scheduler
```

Следите за логами:

```bash
sudo journalctl -u incidentrelay -f
sudo journalctl -u incidentrelay-scheduler -f
```

Откройте:

```text
http://SERVER_IP:8080/login
```

## 7. Опциональный Telegram-воркер

Запускайте этот сервис, только если используется polling Telegram или обработка колбэков:

```bash
sudo systemctl enable --now incidentrelay-telegram-worker
```

Проверьте логи:

```bash
sudo journalctl -u incidentrelay-telegram-worker -f
```

## 8. Обновление IncidentRelay

```bash
sudo dnf update -y incidentrelay
```

Или с помощью `yum`:

```bash
sudo yum update -y incidentrelay
```

После обновления запустите миграции при необходимости:

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py migrate
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

## 9. Удаление IncidentRelay

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
