---
title: Политика хранения данных
description: Настройка автоматического retention для завершённых alerts и диагностических traces.
---

# Политика хранения данных

В IncidentRelay 2.1 появилась единая секция retention для записей базы данных, объём которых со временем может постоянно расти.

Удаление завершённой истории alerts по умолчанию выключено. Настройка выполняется в `[retention]`:

```ini
[retention]
alert_days = 30
# explain_trace_days = 30
# orchestration_execution_days = 30
cleanup_interval_seconds = 86400
batch_size = 500
```

| Параметр | По умолчанию | Описание |
|---|---:|---|
| `alert_days` | `0` | Сколько дней хранить завершённые alert groups и alerts. `0` — хранить бессрочно. |
| `explain_trace_days` | `alert_days` | Необязательный override для Explain Trace. Явный `0` сохраняет standalone traces бессрочно; traces, связанные с удалённой историей alert, всё равно удаляются каскадно. |
| `orchestration_execution_days` | `alert_days` | Необязательный override для обычных execution traces Event Orchestration. Явный `0` хранит их бессрочно. |
| `cleanup_interval_seconds` | `86400` | Как часто запускается единый scheduler job retention. |
| `batch_size` | `500` | Максимальное число alert groups или standalone alerts, удаляемых за одну транзакцию. |

Если `explain_trace_days` или `orchestration_execution_days` не заданы, они наследуют `alert_days`. Поэтому в обычном случае достаточно одного значения, но при необходимости диагностические данные можно хранить меньше или дольше.

## История alerts

Retention отсчитывается от `resolved_at`, а не от времени создания alert. Группа может быть удалена только если:

- статус alert group равен `resolved`;
- `resolved_at` старше retention cutoff;
- каждый alert, всё ещё привязанный к группе, также имеет статус `resolved`.

При удалении подходящей группы зависимая история удаляется через foreign-key cascade. Сюда входят lifecycle events, комментарии, notification delivery records, responder/stakeholder state, применения silence/maintenance, correlation rows, Explain Trace и другие записи, принадлежащие группе. Alerts группы удаляются явно перед самой группой.

Старые standalone alerts без группы также удаляются, если они `resolved` и их `resolved_at` старше cutoff.

Активные, acknowledged, silenced, реактивированные и другие незавершённые инциденты cleanup не выбирает. Audit log сохраняется, поскольку он намеренно хранит scalar object IDs и не владеет alert records.

## Explain Trace

Explain Trace наследует `alert_days`, если явно не задан `explain_trace_days`. Например:

```ini
[retention]
alert_days = 90
explain_trace_days = 30
```

В этом случае завершённая история alerts хранится 90 дней, а standalone Explain Trace — 30 дней. Trace, связанный с alert history, всегда удаляется вместе со своим alert/group, даже если его собственный срок хранения больше.

## Event Orchestration execution traces

Обычные execution traces Event Orchestration наследуют `alert_days`, если не задан `orchestration_execution_days`. Существующие специальные правила retention для dropped events, terminal pending events и webhook executions остаются независимыми и могут удалить соответствующие записи раньше.

## Работа scheduler

IncidentRelay использует один `retention_cleanup_job` и один distributed database lock для retention-прохода 2.1. За один запуск выполняются cleanup alert history, Explain Trace и Event Orchestration retention.

История alerts удаляется батчами, чтобы не создавать одну очень большую транзакцию. В SQLite и PostgreSQL удаление строк делает страницы базы доступными для повторного использования, но не обязательно сразу уменьшает размер файла. Для возврата уже выделенного места операционной системе используйте штатное обслуживание конкретной СУБД в подходящее maintenance window.

## Обновление с 2.0

Новый конфиг должен использовать только `[retention]`.

Для совместимости IncidentRelay 2.1 всё ещё читает старый `[alerts] alert_explain_trace_retention_days`, если `retention.explain_trace_days` отсутствует. Старые настройки интервала cleanup также используются как fallback, если не задан `retention.cleanup_interval_seconds`. Новые значения из `[retention]` всегда имеют приоритет.
