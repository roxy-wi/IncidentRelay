---
title: Релиз IncidentRelay 2.5
description: Переход collaboration на Incident, API и выпускные проверки.
---

# IncidentRelay 2.5

Документ описывает кандидата в релиз. Локальные проверки не заменяют Linux/Python
матрицу CI.

## Изменения

- Incident владеет commander/responders, stakeholders, снимком ServiceOwner,
  операционными комментариями, root cause и resolution summary.
- Workspace объединяет операционную и доступную техническую историю с автором и
  источником. Комментарии AlertGroup остаются техническими. Затронутые сервисы
  содержат инструкции, ссылки, доступные зависимости и агрегированное влияние.
- Изменения Incident защищены `row_version`; участники и responder меняются
  атомарно с событиями и аудитом. При `409` интерфейс сохраняет редактируемый текст
  для согласования с обновлённой записью.
- Доставка сохраняется по событию/каналу/адресату, имеет ограниченные повторы,
  восстановление зависших попыток и подавление дублей. Гарантия —
  [at least once](stakeholders.md#доставка-и-повторы).

`PATCH /api/incidents/<id>` принимает `root_cause` и `resolution_summary` (nullable,
до 10000 символов) вместе с актуальным `row_version`. OpenAPI описывает payload,
ответы collaboration, ограничения и конфликты.
В PATCH значение `null` оставляет поле без изменений; пустая строка очищает
`root_cause` или `resolution_summary`.

## Решение о совместимости

Текущий код удаляет `/api/alert-groups/<id>/responders` и
`/api/alert-groups/<id>/stakeholders`, включая item routes. Миграция 2.5 заменяет
их хранилище данными Incident. Клиенты должны использовать соответствующие
`/api/incidents/<incident_id>/...` и настоящие ID Incident. Автоматического alias
или forwarding старых ID нет.

**Согласовано для 2.5: удаление является breaking change API и хранилища.**
Прежний срок 2.9 для responder/stakeholder routes и storage больше не применяется.
Локальный архитектурный roadmap обновлён в соответствии с этим решением.

Записи без однозначного Incident намеренно пропускаются. Храните проверенную
резервную копию: в новых таблицах их не будет. См. [миграцию и откат](collaboration-migration-2.5.md).

## Выпускные проверки

В отдельной БД с явно заданным `INCIDENTRELAY_CONFIG_FILE`:

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m compileall -q app manage.py run.py
python manage.py migrate
python -m app.check_schema
python -m app.check_templates
python tools/check_duplicate_tests.py
pytest --cov=app --cov-branch --cov-fail-under=50
```

Повторите миграции, проверку схемы и тесты на PostgreSQL 16. Включите PostgreSQL
каталог, исключённый настройкой по умолчанию:

```sh
pytest tests -o 'norecursedirs=.git .venv .tmp __pycache__'
```

Проверьте обновление настоящей схемы 2.4 с однозначными связями, отсутствующими и
неоднозначными связями, а также дублями. Сверьте счётчики, технические комментарии,
новые вставки после сохранённых ID и повторный no-op migrate. Одних unit fixtures
для этой репетиции недостаточно.

Для браузерных проверок установите Node, Playwright и Chromium:

```sh
INCIDENTRELAY_BROWSER_TESTS=1 pytest tests/ux/test_incident_workspace_browser.py
```

Проверяются добавление/удаление, комментарии, сохранение текста при `409`, навигация,
повторное открытие, read-only пользователь, языки, узкий экран и UTC/DST.
POSIX multiprocess metrics и Linux entrypoint должны проходить на Linux:
пропуск или import shim на Windows не подтверждают их работоспособность.

Условия выпуска: зелёные SQLite/PostgreSQL проверки, поддерживаемая Python-матрица,
успешная репетиция обновления.

[Результаты локальной выпускной проверки](release-validation-2.5.md).
