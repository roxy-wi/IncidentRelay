---
title: RPM Installation
description: Install IncidentRelay on RedHat-like distributions from the RPM repository
---

# RPM Installation

Use this guide for RHEL, Rocky Linux, AlmaLinux and CentOS Stream installations.

Repository file:

```text
https://repo.incidentrelay.io/incidentrelay.repo
```

## 1. Install the repository file

For DNF-based systems:

```bash
sudo dnf install -y curl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo dnf makecache
```

For older yum-based systems:

```bash
sudo yum install -y curl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo yum makecache
```

## 2. Install IncidentRelay

```bash
sudo dnf install -y incidentrelay
```

Or with `yum`:

```bash
sudo yum install -y incidentrelay
```

The RPM package installs the application and service files using these paths:

```text
/var/www/incidentrelay                    # application directory
/etc/incidentrelay/incidentrelay.conf     # main configuration file
/var/lib/incidentrelay                    # runtime data, SQLite database by default
/var/log/incidentrelay                    # application logs
/usr/local/lib/incidentrelay/voice_providers # custom voice providers
```

The package should run under the dedicated system user:

```text
incidentrelay
```

## 3. Configure IncidentRelay

Edit:

```bash
sudo vi /etc/incidentrelay/incidentrelay.conf
```

At minimum, review:

```ini
[server]
secret_key =
public_base_url = https://incidentrelay.example.com

[database]
type = sqlite
path = /var/lib/incidentrelay/incidentrelay.db
```

For PostgreSQL, use:

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

## 4. Run database migrations

The RPM package may run migrations during installation. If the database was not ready during install, run migrations manually after editing the config:

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py migrate
```

## 5. Create the first admin user

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

Change the password and email before production use.

## 6. Start services

Enable and start the web service and scheduler:

```bash
sudo systemctl enable --now incidentrelay
sudo systemctl enable --now incidentrelay-scheduler
```

Check service status:

```bash
sudo systemctl status incidentrelay
sudo systemctl status incidentrelay-scheduler
```

Follow logs:

```bash
sudo journalctl -u incidentrelay -f
sudo journalctl -u incidentrelay-scheduler -f
```

Open:

```text
http://SERVER_IP:8080/login
```

## 7. Optional Telegram worker

Start this service only if Telegram polling or callback processing is used:

```bash
sudo systemctl enable --now incidentrelay-telegram-worker
```

Check logs:

```bash
sudo journalctl -u incidentrelay-telegram-worker -f
```

## 8. Upgrade IncidentRelay

```bash
sudo dnf update -y incidentrelay
```

Or with `yum`:

```bash
sudo yum update -y incidentrelay
```

After upgrade, run migrations if needed:

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py migrate
```

Then restart services:

```bash
sudo systemctl restart incidentrelay
sudo systemctl restart incidentrelay-scheduler
```

If Telegram worker is used:

```bash
sudo systemctl restart incidentrelay-telegram-worker
```

## 9. Remove IncidentRelay

```bash
sudo dnf remove -y incidentrelay
```

Or with `yum`:

```bash
sudo yum remove -y incidentrelay
```

Configuration and runtime data may remain on disk depending on package removal policy. Remove them manually only when you are sure the data is no longer needed:

```bash
sudo rm -rf /etc/incidentrelay
sudo rm -rf /var/lib/incidentrelay
sudo rm -rf /var/log/incidentrelay
```
