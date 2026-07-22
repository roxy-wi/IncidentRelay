---
title: Демонстрационные данные
description: Создание и проверка демонстрационных данных IncidentRelay для локального тестирования.
---

# Демонстрационные данные

Используйте демонстрационные данные только для локального тестирования и разработки.

Типовая демонстрационная конфигурация создаёт:

- группу;
- пользователей;
- команду;
- ротацию;
- сервисы;
- ссылки сервисов и runbook'и;
- маршрут и каналы;
- токены приёма маршрута (route intake token);
- примеры алертов.

Не используйте демонстрационные пароли, токены или URL вебхуков в продакшене.

## Сервисы в демонстрационных данных

Если демонстрационные данные создают сервисы, используйте их для проверки:

- назначения сервиса по умолчанию для маршрута;
- правил сопоставления сервисов;
- ссылок в контексте алерта;
- runbook'ов в уведомлениях об алертах;
- зависимостей сервисов;
- аналитики сервисов и представлений влияния (impact).

Рекомендуемые примеры демонстрационных сервисов:

```text
Service: RabbitMQ Cloud
Slug: rabbitmq-cloud
Type: queue
Environment: production
Criticality: critical

Service: Billing API
Slug: billing-api
Type: api
Environment: production
Criticality: high

Service: PostgreSQL Prod
Slug: postgresql-prod
Type: database
Environment: production
Criticality: critical
```

Рекомендуемые примеры демонстрационных ссылок:

```text
Grafana dashboard
Logs
Repository
Documentation
```

Рекомендуемые примеры демонстрационных runbook'ов:

```text
Generic service troubleshooting
RabbitMQ cluster partition
Database connection errors
```

Если демонстрационные данные пока не включают сервисы, создайте сервис вручную на странице Services, чтобы проверить ссылки сервисов, runbook'и и представления влияния.
