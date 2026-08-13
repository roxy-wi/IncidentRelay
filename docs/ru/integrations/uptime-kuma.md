---
title: Uptime Kuma
description: Передача изменений состояния мониторов Uptime Kuma в IncidentRelay и автоматическое закрытие алертов после восстановления мониторов.
---

# Интеграция с Uptime Kuma

Uptime Kuma проверяет доступность сайтов, API, хостов, портов и других целей. IncidentRelay превращает изменения состояния мониторов в алерты, требующие действий, направляет их ответственной команде, запускает настроенный процесс уведомлений и эскалаций, а после восстановления монитора закрывает тот же алерт.

Используйте интеграцию для следующего процесса:

```text
Uptime Kuma обнаруживает DOWN
    -> IncidentRelay создаёт или обновляет алерт
    -> правила маршрутов, сервисов и оркестрации определяют владельца
    -> дежурные пользователи получают уведомления
    -> Uptime Kuma обнаруживает UP
    -> IncidentRelay закрывает существующий алерт
```

Встроенная интеграция понимает стандартное JSON-тело Webhook от Uptime Kuma. Создавать собственный шаблон payload не требуется.

Эндпоинт:

```text
POST /api/integrations/uptime-kuma
```

## Для чего полезна интеграция

Типичные примеры:

- публичный сайт перестал отвечать;
- внутренний API возвращает ошибки или превышает время ожидания;
- TCP-порт недоступен;
- сервер перестал отвечать на ping;
- проверка DNS завершилась ошибкой;
- изменилось состояние монитора сертификата или ключевого слова;
- несколько мониторов нужно направлять разным командам с помощью тегов Uptime Kuma;
- кратковременные сбои нужно задерживать, подавлять или дополнять данными с помощью Event Orchestration.

Uptime Kuma выполняет проверку. IncidentRelay управляет операционным реагированием: назначением, уведомлениями, эскалациями, подтверждением, группировкой инцидентов, влиянием на сервисы, комментариями, временной шкалой и историей аудита.

## Перед началом

Вам понадобятся:

1. группа и команда IncidentRelay;
2. хотя бы один канал уведомлений или другой способ доставки;
3. маршрут с источником **Uptime Kuma**;
4. доступ к настройкам уведомлений Uptime Kuma;
5. HTTPS-URL, доступный из Uptime Kuma.

Токен приёма принадлежит одному маршруту IncidentRelay. Храните его в секрете. Любой, у кого есть токен, может отправлять события в этот маршрут.

## Шаг 1: создайте маршрут в IncidentRelay

1. Откройте **Routes**.
2. Нажмите **Create route**.
3. Выберите группу и команду, которые должны изначально владеть алертами.
4. В поле **Source** выберите **Uptime Kuma**.
5. Укажите понятное имя маршрута, например `Uptime Kuma production`.
6. Подключите каналы, которые должны получать уведомления об алертах.
7. Сохраните маршрут.
8. Откройте сведения о приёме событий маршрутом и скопируйте:
   - URL приёма;
   - bearer-токен;
   - пример запроса.

Для встроенного маршрута Uptime Kuma IncidentRelay использует следующий эндпоинт:

```text
https://incidentrelay.example.com/api/integrations/uptime-kuma
```

Новые маршруты Uptime Kuma по умолчанию группируют события по `uptime_kuma_monitor_id`. Благодаря этому повторные события DOWN и последующее событие UP остаются привязаны к одному инциденту монитора.

## Шаг 2: настройте Uptime Kuma

В Uptime Kuma:

1. Откройте **Settings**.
2. Откройте **Notifications**.
3. Нажмите **Setup Notification**.
4. Выберите **Webhook**.
5. Укажите понятное имя, например `IncidentRelay`.
6. В качестве URL webhook укажите URL приёма IncidentRelay.
7. Выберите метод `POST`.
8. Выберите тип содержимого JSON / `application/json`.
9. Добавьте заголовок авторизации, показанный ниже.
10. Оставьте стандартное тело запроса Uptime Kuma.
11. Сохраните уведомление.
12. Подключите его к каждому монитору, который должен создавать алерты IncidentRelay.

Дополнительные заголовки:

```json
{
  "Authorization": "Bearer INCIDENTRELAY_ROUTE_TOKEN"
}
```

Не помещайте токен в строку запроса. Не переходите на пользовательское тело запроса, если только вы намеренно не воспроизводите стандартные поля `heartbeat`, `monitor` и `msg`, описанные ниже.

После сохранения воспользуйтесь кнопкой **Test** в Uptime Kuma. Тестовое уведомление может не содержать настоящий монитор или heartbeat. IncidentRelay принимает его как информационное тестовое событие, чтобы можно было проверить соединение и аутентификацию.

## Сопоставление жизненного цикла

Uptime Kuma передаёт числовое состояние в `heartbeat.status`. IncidentRelay сопоставляет его следующим образом:

| Состояние Uptime Kuma | Значение | Жизненный цикл IncidentRelay |
| --- | --- | --- |
| `0` | DOWN | `firing` |
| `1` | UP | `resolved` |
| `2` | PENDING | `firing` |
| `3` | MAINTENANCE | `resolved` |

Уведомление DOWN или PENDING создаёт новый алерт либо обновляет существующий алерт этого монитора. Уведомление UP закрывает его. MAINTENANCE также считается состоянием resolved, чтобы намеренно переведённый в режим обслуживания монитор не продолжал будить дежурного пользователя.

Если присутствует идентификатор монитора, IncidentRelay использует следующий стабильный ключ дедупликации:

```text
uptime-kuma:<monitor id>
```

Например, монитор `42` создаёт ключ:

```text
uptime-kuma:42
```

Идентификатор монитора должен оставаться одинаковым в событиях DOWN и UP. Для стандартного payload webhook Uptime Kuma это условие обычно выполняется.

## Пример payload DOWN

Стандартное уведомление похоже на следующий упрощённый payload:

```json
{
  "heartbeat": {
    "monitorID": 42,
    "status": 0,
    "time": "2026-07-27 12:10:00.000",
    "msg": "Request timeout after 48000ms",
    "ping": null,
    "duration": 48
  },
  "monitor": {
    "id": 42,
    "name": "Payments API",
    "type": "http",
    "url": "https://payments.example.com/health",
    "tags": [
      {"name": "team", "value": "sre"},
      {"name": "service", "value": "payments"},
      {"name": "environment", "value": "production"},
      {"name": "severity", "value": "critical"}
    ]
  },
  "msg": "[Payments API] [DOWN] Request timeout"
}
```

IncidentRelay приблизительно нормализует его до следующего вида:

```json
{
  "source": "uptime_kuma",
  "status": "firing",
  "title": "Payments API",
  "message": "Request timeout after 48000ms",
  "severity": "critical",
  "team_slug": "sre",
  "dedup_key": "uptime-kuma:42"
}
```

## Пример payload восстановления

Когда монитор восстанавливается, Uptime Kuma отправляет тот же идентификатор монитора со статусом `1`:

```json
{
  "heartbeat": {
    "monitorID": 42,
    "status": 1,
    "time": "2026-07-27 12:12:30.000",
    "msg": "200 - OK",
    "ping": 84
  },
  "monitor": {
    "id": 42,
    "name": "Payments API",
    "type": "http",
    "url": "https://payments.example.com/health"
  },
  "msg": "[Payments API] [UP] 200 - OK"
}
```

Поскольку ключ дедупликации остаётся равным `uptime-kuma:42`, IncidentRelay закрывает существующий алерт, а не создаёт отдельный алерт о восстановлении.

## Метки, создаваемые IncidentRelay

Нормализатор добавляет метки, удобные для сопоставления:

| Метка | Пример | Назначение |
| --- | --- | --- |
| `uptime_kuma_monitor_id` | `42` | Стабильный идентификатор монитора и группировка. |
| `uptime_kuma_monitor_name` | `Payments API` | Понятное пользователю имя монитора. |
| `uptime_kuma_monitor_type` | `http` | HTTP, ping, port и другие типы мониторов. |
| `uptime_kuma_status` | `down` | `down`, `up`, `pending` или `maintenance`. |
| `uptime_kuma_status_code` | `0` | Исходное числовое состояние. |
| `uptime_kuma_target` | `https://.../health` | Проверяемый URL либо хост и порт. |
| `uptime_kuma_hostname` | `db-01.example.com` | Имя хоста, если присутствует. |
| `uptime_kuma_port` | `5432` | Порт, если присутствует. |
| `uptime_kuma_ping_ms` | `84` | Последнее время ответа, если присутствует. |
| `uptime_kuma_duration_seconds` | `48` | Длительность сбоя или проверки, если присутствует. |
| `uptime_kuma_local_datetime` | `2026-07-27 ...` | Время, переданное Uptime Kuma. |
| `event_link` | `https://...` | Ссылка на проверяемую HTTP-цель или переданная ссылка монитора. |

Полное исходное тело webhook также сохраняется как необработанный payload интеграции для просмотра и сопоставления в оркестрации.

## Использование тегов Uptime Kuma для маршрутизации

Теги позволяют одной общей интеграции уведомлений Uptime Kuma обслуживать много команд и сервисов.

Рекомендуемые теги:

```text
team=sre
service=payments
environment=production
severity=critical
region=eu-west
cluster=payments-primary
```

Интеграция предоставляет каждый тег с безопасным префиксом:

```text
uptime_kuma_tag_team=sre
uptime_kuma_tag_service=payments
uptime_kuma_tag_environment=production
```

Распространённые теги маршрутизации дополнительно предоставляются без префикса:

```text
team=sre
service=payments
environment=production
severity=critical
region=eu-west
cluster=payments-primary
```

Тег `team` или `oncall_team` может выбирать `team_slug`. Тег `severity` или `priority` используется как нормализованная серьёзность алерта, если содержит поддерживаемое значение.

Используйте согласованные имена тегов во всех мониторах. Предпочитайте имена в нижнем регистре и стабильные значения. Например, везде используйте `environment=production`, а не смесь `prod`, `production` и `Production`, если ваши правила сопоставления специально не учитывают все варианты.

## Использование с Event Orchestration

Event Orchestration может дополнять события Uptime Kuma данными или направлять их до запуска обычного жизненного цикла алерта.

### Маршрутизация всех событий Uptime Kuma

Условие:

```text
event.source equals uptime_kuma
```

Возможные действия:

```text
set_team -> Platform SRE
set_route -> Uptime Kuma production
stop
```

### Маршрутизация одного сервиса по тегам

Условия:

```text
ALL
├── event.source equals uptime_kuma
├── labels.service equals payments
└── labels.environment equals production
```

Действия:

```text
set_team -> Payments on-call
set_service -> Payments API
set_priority -> P1
stop
```

### Задержка коротких сбоев

Многие проверки доступности восстанавливаются после одного неудачного запроса. Чтобы уведомлять дежурного только при продолжающемся сбое:

```text
IF event.source equals uptime_kuma
AND labels.uptime_kuma_status equals down
THEN pause 120 seconds
     retrigger preserve
     reason "Wait for a transient outage to recover"
```

Если уведомление UP поступает в течение двух минут, ожидающее событие закрывается без создания активного алерта. Перед публикацией проверьте такое поведение в Simulator и Replay.

### Повышение серьёзности для критического монитора

```text
ALL
├── event.source equals uptime_kuma
├── labels.uptime_kuma_tag_tier equals critical
└── labels.environment equals production
```

Действие:

```text
set_severity -> critical
```

### Объединение связанных мониторов в один инцидент

Предположим, несколько мониторов проверяют разные эндпоинты одного сервиса. Их можно объединить в одну группу алертов, сохраняя по одному дочернему алерту для каждого монитора:

```text
group_key: uptime-kuma:{{ labels.service }}:{{ labels.environment }}
dedup_key: uptime-kuma:{{ labels.uptime_kuma_monitor_id }}
window_seconds: 900
```

Прежде чем менять группировку или добавлять в production действия `pause`, `suppress` либо `drop`, прочитайте [руководство пользователя Event Orchestration](../usage/event-orchestration.md).

## Проверка с помощью curl

Замените URL и токен:

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/uptime-kuma' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "heartbeat": {
      "monitorID": 42,
      "status": 0,
      "msg": "Connection refused",
      "ping": null
    },
    "monitor": {
      "id": 42,
      "name": "PostgreSQL",
      "type": "port",
      "hostname": "db-01.example.com",
      "port": 5432,
      "tags": [
        {"name": "team", "value": "database"},
        {"name": "service", "value": "postgresql"},
        {"name": "environment", "value": "production"}
      ]
    },
    "msg": "[PostgreSQL] [DOWN] Connection refused"
  }'
```

Затем отправьте событие UP с тем же идентификатором монитора:

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/uptime-kuma' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "heartbeat": {
      "monitorID": 42,
      "status": 1,
      "msg": "TCP connection succeeded",
      "ping": 12
    },
    "monitor": {
      "id": 42,
      "name": "PostgreSQL",
      "type": "port",
      "hostname": "db-01.example.com",
      "port": 5432
    },
    "msg": "[PostgreSQL] [UP] TCP connection succeeded"
  }'
```

Второй ответ должен ссылаться на тот же алерт и ту же группу и сообщать о состоянии resolved.

## Что происходит при неверном маршруте

Эндпоинт проверяет, что bearer-токен принадлежит маршруту с источником `uptime_kuma`.

Распространённые ответы:

| Ответ | Значение |
| --- | --- |
| `401 Route intake token is required` | Заголовок авторизации отсутствует или имеет неверный формат. |
| `401 Invalid or disabled route intake token` | Токен неверен, был заменён либо маршрут отключён. |
| `400 Route source must be uptime_kuma` | Токен принадлежит маршруту другого источника интеграции. |
| Ответ валидации `422` | В JSON-теле недостаточно данных Uptime Kuma. |

Не используйте для этого эндпоинта токен Alertmanager, Grafana или Generic Webhook. Создайте отдельный маршрут Uptime Kuma.

## Устранение неполадок

### Тест Uptime Kuma успешен, но настоящие мониторы не отправляют уведомления

- Откройте монитор и убедитесь, что для него включено уведомление IncidentRelay.
- Убедитесь, что уведомления включены для событий DOWN и восстановления.
- Проверьте логи уведомлений Uptime Kuma.
- Убедитесь, что URL доступен из контейнера или хоста Uptime Kuma, а не только из вашего браузера.

### IncidentRelay возвращает 401

- Убедитесь, что заголовок имеет точный вид `Authorization: Bearer TOKEN`.
- Удалите случайные кавычки вокруг полного значения заголовка.
- Проверьте, не был ли заменён токен маршрута.
- Убедитесь, что обратный прокси передаёт заголовок `Authorization`.

### IncidentRelay сообщает о несовпадении источника маршрута

Токен принадлежит маршруту, созданному для другого источника. Откройте **Routes**, создайте или отредактируйте маршрут с источником **Uptime Kuma** и скопируйте его токен приёма.

### DOWN создаёт алерт, но UP не закрывает его

Сравните два исходных payload:

- оба должны содержать одинаковый `monitor.id` или `heartbeat.monitorID`;
- событие восстановления должно содержать `heartbeat.status=1`;
- оркестрация не должна заменять ключ дедупликации изменяющимся значением;
- для группировки маршрута следует использовать стабильные метки, предпочтительно `uptime_kuma_monitor_id`.

### Каждое уведомление создаёт новый алерт

- Проверьте наличие стандартного идентификатора монитора.
- Не используйте временные метки в действиях оркестрации `set_dedup_key` или `set_grouping`.
- Убедитесь, что события DOWN и UP используют один маршрут.

### Теги недоступны для сопоставления

Проверьте исходный объект монитора. Теги должны находиться в `monitor.tags`. Старые или изменённые payload Uptime Kuma могут их не содержать. При этом можно сопоставлять события по идентификатору, имени и типу монитора, имени хоста или цели.

### Заголовок алерта слишком общий

Настоящее уведомление монитора должно содержать `monitor.name`. Если оно отсутствует, IncidentRelay использует общий заголовок `Uptime Kuma notification`. Имена мониторов должны быть понятными и достаточно уникальными для операторов.

## Рекомендации по безопасности

- Используйте HTTPS между Uptime Kuma и IncidentRelay.
- Используйте отдельный маршрут и токен для Uptime Kuma.
- Не добавляйте токен в имена, сообщения, теги или URL мониторов.
- Замените токен маршрута, если он стал доступен посторонним.
- По возможности ограничьте сетевой доступ к эндпоинту приёма.
- Оставьте стандартное JSON-тело, если пользовательское тело не является необходимым и проверенным.
- При использовании шаблонов или webhook-действий считайте сообщения и теги мониторов недоверенными внешними данными.
- Перед публикацией действий, которые отбрасывают, подавляют, задерживают события или вызывают внешние webhook'и, проверьте оркестрацию в Simulator либо в режиме shadow.

## Операционный чек-лист

Перед широким включением интеграции:

- [ ] Маршрут Uptime Kuma использует источник `uptime_kuma`.
- [ ] Bearer-токен сохранён в Additional Headers.
- [ ] Включено стандартное JSON-тело.
- [ ] Тестовое уведомление поступает в IncidentRelay.
- [ ] Настоящее событие DOWN создаёт один алерт.
- [ ] Настоящее событие UP закрывает тот же алерт.
- [ ] Теги команды и сервиса соответствуют существующим объектам IncidentRelay или правилам оркестрации.
- [ ] Каналы уведомлений достигают нужного дежурного пользователя.
- [ ] Перед публикацией Event Orchestration проверена симуляцией.
- [ ] Документированы порядок ротации токена и ответственные за него.
