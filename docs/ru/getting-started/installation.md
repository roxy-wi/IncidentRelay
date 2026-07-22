---
title: Установка
description: Навигация по руководствам установки для разных методов развёртывания IncidentRelay.
---

# Установка

Эта страница сохранена как краткий диспетчер для старых ссылок.

Выберите одно из актуальных руководств по установке:

| Метод | Руководство |
|---|---|
| Docker Compose | [Установка через Docker](docker.md) |
| RPM-пакет для дистрибутивов на основе RedHat | [Установка через RPM](rpm-installation.md) |
| Ручная выгрузка исходников с systemd | [Ручная установка с systemd](systemd.md) |

Не используйте старые команды, такие как `python app/migrate.py migrate` или `python scheduler.py`. Текущие инсталляции используют:

```bash
python manage.py migrate
python -m app.scheduler_worker
```
