---
title: Installation
description: Installation guide dispatcher for IncidentRelay deployment methods.
---

# Installation

This page is kept as a short dispatcher for older links.

Choose one of the current installation guides:

| Method | Guide |
|---|---|
| Docker Compose | [Docker Installation](docker.md) |
| Kubernetes with Helm | [Kubernetes Installation](kubernetes.md) |
| RPM package for RedHat-like distributions | [RPM Installation](rpm-installation.md) |
| Manual source checkout with systemd | [Manual systemd Installation](systemd.md) |

Do not use old commands such as `python app/migrate.py migrate` or `python scheduler.py`. Current installations use:

```bash
python manage.py migrate
python -m app.scheduler_worker
```
