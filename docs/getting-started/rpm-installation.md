---
title: RPM Installation
description: Install and verify IncidentRelay on RedHat-like distributions from the RPM repository
---

# RPM Installation

Use this guide for RHEL, Rocky Linux, AlmaLinux and CentOS Stream installations.

!!! warning
    A successful `dnf install` transaction only confirms that the RPM files were
    unpacked. Do not expose the service until the Python runtime, configuration,
    migrations and readiness checks below all succeed.

Repository file:

```text
https://repo.incidentrelay.io/incidentrelay.repo
```

## 1. Install the repository file

For DNF-based systems:

```bash
sudo dnf install -y curl openssl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo dnf makecache
```

For older yum-based systems:

```bash
sudo yum install -y curl openssl
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

## 3. Verify the packaged Python runtime

IncidentRelay requires Python 3.10 or newer. EL9 provides Python 3.9 as
`/usr/bin/python3`, so the web service and scheduler must use the packaged venv,
not the system interpreter.

```bash
rpm -q incidentrelay
sudo test -x /var/www/incidentrelay/venv/bin/python
/var/www/incidentrelay/venv/bin/python --version
/var/www/incidentrelay/venv/bin/python -c \
  'import flask, peewee, gunicorn, joserfc; print("Python dependencies: OK")'
```

The version command must report Python 3.10 or newer and the import command must
finish without an exception.

### Repair an incomplete RPM 2.0-1 runtime on EL9

Some `incidentrelay-2.0-1` builds install the application files but leave the
services on Python 3.9 or omit runtime dependencies. Preserve the packaged venv,
create a Python 3.11 venv and install the application requirements:

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

If a pinned dependency in the RPM requirements file is unavailable, update to a
fixed RPM build. Versions validated as a temporary recovery with 2.0-1 are
`regex==2026.1.15`, `pyTelegramBotAPI==4.32.0` and `Authlib==1.6.12`.

After repairing the venv, repeat the import check above.

## 4. Configure IncidentRelay

Edit:

```bash
sudo vi /etc/incidentrelay/incidentrelay.conf
```

Generate two different secrets with `openssl rand -hex 32`, then review at least:

```ini
[main]
secret_key = replace-with-the-first-random-value
timezone = UTC

[server]
public_base_url = https://incidentrelay.example.com

[database]
type = sqlite
name = /var/lib/incidentrelay/incidentrelay.db

[auth]
jwt_secret = replace-with-the-second-random-value
jwt_cookie_secure = true
```

`secret_key` belongs to `[main]`, not `[server]`. SQLite uses `name`, not
`path`, for the database file. Keep `secret_key` and `jwt_secret` non-empty,
different and stable across restarts. Use the real DNS name or public IP in
`public_base_url`; set `jwt_cookie_secure = true` for HTTPS.

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

The 2.0-1 example config may contain duplicate
`alert_group_window_seconds` or `callback_secret` entries. Keep each option only
once and validate the complete file:

```bash
sudo -u incidentrelay \
  /var/www/incidentrelay/venv/bin/python -c \
  'from configparser import ConfigParser; p="/etc/incidentrelay/incidentrelay.conf"; c=ConfigParser(interpolation=None, strict=True); c.read(p); print("Configuration: OK")'
```

Set restrictive permissions and ensure the runtime directories are writable by
the service account:

```bash
sudo chown root:incidentrelay /etc/incidentrelay/incidentrelay.conf
sudo chmod 0640 /etc/incidentrelay/incidentrelay.conf
sudo chown -R incidentrelay:incidentrelay \
  /var/lib/incidentrelay /var/log/incidentrelay
sudo chmod 0750 /var/lib/incidentrelay /var/log/incidentrelay
```

## 5. Make both systemd services use the venv

Inspect the effective units:

```bash
sudo systemctl cat incidentrelay
sudo systemctl cat incidentrelay-scheduler
```

If either unit uses `/usr/bin/python3` or a global `gunicorn`, add systemd
drop-ins. For SQLite, keep one web worker:

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

Apply the changes:

```bash
sudo systemctl daemon-reload
```

## 6. Run database migrations and check the schema

The RPM package may run migrations during installation. If the database was not ready during install, run migrations manually after editing the config:

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

Both commands must exit with status 0.

## 7. Create the first admin user

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

Change the password and email before production use.

## 8. Start and verify services

Enable and start the web service and scheduler:

```bash
sudo systemctl enable --now incidentrelay
sudo systemctl enable --now incidentrelay-scheduler
```

Check service status:

```bash
sudo systemctl status incidentrelay
sudo systemctl status incidentrelay-scheduler
curl -fsS http://127.0.0.1:8080/readyz
```

Follow logs:

```bash
sudo journalctl -u incidentrelay -f
sudo journalctl -u incidentrelay-scheduler -f
```

The packaged service listens on `127.0.0.1:8080`. Do not open port 8080 to the
Internet. Put Nginx or another reverse proxy on ports 80 and 443, configure TLS,
and expose only those ports. On SELinux-enabled systems, allow Nginx to connect
to the local upstream:

```bash
sudo setsebool -P httpd_can_network_connect 1
```

After configuring the proxy, verify from another machine and open:

```text
https://YOUR_PUBLIC_NAME_OR_IP/readyz
https://YOUR_PUBLIC_NAME_OR_IP/login
```

A public IP can use a Let's Encrypt IP certificate with Certbot 5.4 or newer and
the `shortlived` profile. IP certificates are valid for about six days and need
reliable automatic renewal. See the
[Let's Encrypt instructions](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/).

## 9. Optional Telegram worker

Start this service only if Telegram polling or callback processing is used:

```bash
sudo systemctl enable --now incidentrelay-telegram-worker
```

Check logs:

```bash
sudo journalctl -u incidentrelay-telegram-worker -f
```

## 10. Upgrade IncidentRelay

!!! warning "Upgrading from 1.2 to 2.1 or later"
    IncidentRelay 2.1 blocks private/loopback/link-local/reserved outbound HTTP
    destinations unless they are explicitly allowed. Existing internal OIDC
    metadata/JWKS endpoints and outgoing webhooks/API integrations can therefore
    stop working immediately after the upgrade.

Before upgrading, identify internal endpoints used by IncidentRelay and add the
smallest required CIDRs/IPs to the existing configuration:

```ini
[security]
outbound_private_network_allowlist = 10.20.0.0/16,192.168.50.10/32
```

The RPM installs `incidentrelay.conf` as a `noreplace` configuration file, so
an existing configuration is preserved during upgrade. Check for
`/etc/incidentrelay/incidentrelay.conf.rpmnew`, but do not assume the new
security option was merged into your active file automatically. See
[Outbound HTTP network policy](configuration.md#outbound-http-network-policy)
for the DNS behavior and additional examples.

```bash
sudo dnf update -y incidentrelay
```

Or with `yum`:

```bash
sudo yum update -y incidentrelay
```

After upgrade, run migrations if needed:

```bash
cd /var/www/incidentrelay
sudo -u incidentrelay env \
  PYTHONPATH=/var/www/incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python manage.py migrate
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

## 11. Remove IncidentRelay

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
