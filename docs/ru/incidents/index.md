---
title: Управление инцидентами
description: Граница first-class Incident и технических AlertGroup в IncidentRelay 2.3.
---

# Управление инцидентами

IncidentRelay 2.3 разделяет обработку технических сигналов и операционное расследование:

```text
Alert -> AlertGroup -> optional Incident
```

AlertGroup отвечает за grouping, технический статус, ACK/resolve, уведомления, эскалацию, технического assignee и технические комментарии. First-class Incident имеет независимый workflow, priority, service context и операционного assignee.

AlertGroup может существовать без Incident. Incident может существовать без AlertGroup, а один Incident может недеструктивно связывать несколько AlertGroup.

## API

- `/api/alert-groups` — технические AlertGroup.
- `/api/incidents` — first-class операционные Incident.
- [Миграция API 2.3](api-migration-2.3.md) — несовместимые изменения endpoint'ов и идентификаторов.

Старый контракт `/api/incidents == AlertGroup` не сохраняется.

## Граница collaboration в 2.3

Технические комментарии остаются на AlertGroup. Legacy responders и stakeholders в 2.3 также остаются AlertGroup-scoped; их канонический перенос в Incident относится к 2.5.

## Рекомендуемое чтение

1. [Алерты и AlertGroup](../usage/alerts.md)
2. [Миграция API 2.3](api-migration-2.3.md)
3. [Архитектура Incident Management v2](../architecture/incident-management-v2.md)
4. [Приоритеты Incident](priorities.md)
5. [Комментарии AlertGroup](../usage/alert-comments.md)
