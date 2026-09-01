# Интеграция с Grafana Alerting

IncidentRelay может принимать уведомления Grafana Alerting через отдельный эндпоинт-вебхук. Каждый экземпляр алерта Grafana нормализуется, маршрутизируется, группируется, дедуплицируется и обрабатывается через стандартный жизненный цикл алертов IncidentRelay.

## Эндпоинт

```text
POST /api/integrations/grafana
```

Эндпоинт требует токен приёма активного маршрута IncidentRelay, источником которого является `grafana`.

```http
Authorization: Bearer <route-intake-token>
Content-Type: application/json
```

## Создание маршрута IncidentRelay

1. Откройте **Routes** в IncidentRelay.
2. Создайте маршрут или отредактируйте существующий.
3. Выберите **Grafana** в качестве источника.
4. Выберите команду, которой принадлежат алерты.
5. Настройте матчеры, группировку и цель назначения.
6. Убедитесь, что маршрут активен.
7. Скопируйте сгенерированный URL приёма и токен маршрута.

Типовая конфигурация группировки:

```json
[
  "alertname",
  "grafana_folder",
  "instance"
]
```

Выбирайте только те метки, которые идентифицируют логический инцидент. Избегайте группировки по меткам, значения которых часто меняются.

Пример матчеров маршрута:

```json
{
  "environment": "production",
  "team": "sre"
}
```

Метки Grafana становятся доступны матчерам маршрута после слияния общих меток и меток отдельных алертов.

## Настройка Grafana

В Grafana:

1. Откройте **Alerts & IRM → Alerting → Notification configuration**.
2. Откройте вкладку **Contact points**.
3. Добавьте точку контакта (contact point).
4. Выберите **Webhook** в качестве интеграции.
5. Укажите URL эндпоинта Grafana IncidentRelay:

   ```text
   https://incidentrelay.example.com/api/integrations/grafana
   ```

6. Установите HTTP-метод `POST`.
7. В настройках авторизации задайте:
   - **Authentication Header Scheme:** `Bearer`
   - **Authentication Header Credentials:** токен маршрута IncidentRelay
8. Оставьте **Disable resolved message** отключённым, чтобы IncidentRelay получал уведомления о восстановлении.
9. Сохраните точку контакта.
10. Используйте тестовое действие Grafana для проверки доставки.

Привяжите точку контакта к нужной политике уведомлений Grafana.


### Пример provisioning-конфигурации Grafana

Grafana OSS/Enterprise позволяет создать contact point из файла в каталоге `provisioning/alerting`:

```yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: IncidentRelay
    receivers:
      - uid: incidentrelay-webhook
        type: webhook
        disableResolveMessage: false
        settings:
          url: https://incidentrelay.example.com/api/integrations/grafana
          httpMethod: POST
          authorization_scheme: Bearer
          authorization_credentials: $INCIDENTRELAY_ROUTE_TOKEN
```

Передайте `INCIDENTRELAY_ROUTE_TOKEN` через окружение процесса/контейнера Grafana вместо хранения токена в provisioning-файле. Оставьте `disableResolveMessage: false`, чтобы IncidentRelay получал события восстановления.

Например, сохраните файл как:

```text
/etc/grafana/provisioning/alerting/incidentrelay.yaml
```

После этого перезапустите Grafana или перезагрузите provisioned alerting resources через provisioning API Grafana. Contact point всё равно нужно выбрать в alert rule или notification policy.

## Рекомендуемые метки Grafana

Добавьте стабильные метки к правилам алертов Grafana, чтобы IncidentRelay мог предсказуемо маршрутизировать и группировать их.

```yaml
labels:
  team: sre
  environment: production
  severity: critical
```

Полезные метки включают:

| Метка | Назначение |
|---|---|
| `team` | Маршрутизация по команде |
| `environment` | Production, staging, development |
| `severity` | Приоритет алерта |
| `service` | Затронутый сервис |
| `instance` | Затронутый хост или инстанс |
| `grafana_folder` | Папка Grafana |
| `alertname` | Имя правила алерта |

Нормализатор также распознаёт `oncall_team` как запасную метку команды, а `priority` или `level` — как запасные метки важности.

## Нормализация алертов

IncidentRelay обрабатывает каждый объект в массиве `alerts` Grafana независимо.

### Статус

Статус экземпляра алерта имеет приоритет над статусом уведомления верхнего уровня.

Значения, похожие на resolved, нормализуются в:

```text
resolved
```

Остальные значения трактуются как:

```text
firing
```

Это позволяет одной группе уведомлений Grafana содержать экземпляры алертов с разными состояниями.

### Заголовок

IncidentRelay выбирает первое доступное значение из:

1. `annotations.summary`
2. `labels.alertname`
3. `title` верхнего уровня
4. `Grafana alert`

### Сообщение

IncidentRelay выбирает первое доступное значение из:

1. `annotations.description`
2. `annotations.message`
3. `message` верхнего уровня
4. `valueString`

### Важность

IncidentRelay выбирает первую доступную метку из:

1. `severity`
2. `priority`
3. `level`

### Команда

IncidentRelay выбирает первое доступное значение из:

1. `labels.team`
2. `labels.oncall_team`
3. `team` верхнего уровня

Приоритет остаётся за сопоставлением маршрута. Метка не обходит обычные проверки доступа к маршруту или проверки матчеров.

## Метки, добавляемые IncidentRelay

При наличии в полезной нагрузке Grafana интеграция предоставляет следующие значения в виде меток:

| Метка IncidentRelay | Поле Grafana |
|---|---|
| `dashboard_url` | `dashboardURL` |
| `panel_url` | `panelURL` |
| `generator_url` | `generatorURL` |
| `silence_url` | `silenceURL` |
| `grafana_url` | `externalURL` |
| `grafana_org_id` | `orgId` |
| `grafana_receiver` | `receiver` |
| `grafana_group_key` | `groupKey` |
| `grafana_state` | `state` |

Первая доступная ссылка Grafana также сохраняется как `event_link`. Порядок выбора:

1. URL дашборда
2. URL панели
3. URL правила алерта
4. URL заглушки
5. базовый URL Grafana

## Дедупликация

Когда Grafana предоставляет `fingerprint`, IncidentRelay использует его в качестве ключа дедупликации.

Когда `fingerprint` отсутствует, IncidentRelay генерирует стабильный ключ из:

- источника Grafana;
- UID правила алерта, если доступен;
- заголовка алерта;
- стабильных меток;
- ID организации Grafana.

Уведомление firing, за которым следует уведомление resolved с тем же ключом дедупликации, обновляет существующий алерт, а не создаёт новый.

## Сохранённая полезная нагрузка

IncidentRelay сохраняет исходный контекст группы Grafana, но каждый нормализованный алерт IncidentRelay хранит в сохранённом массиве `alerts` только свой собственный экземпляр алерта Grafana.

Это сохраняет такие поля, как:

- `orgId`;
- `receiver`;
- `groupKey`;
- общие метки и аннотации;
- ссылки на дашборд и панель;
- значения выражений;
- временные метки.

## Пример полезной нагрузки

```json
{
  "receiver": "incidentrelay",
  "status": "firing",
  "orgId": 1,
  "groupKey": "{}:{alertname=\"DiskFull\"}",
  "commonLabels": {
    "team": "sre",
    "environment": "production"
  },
  "commonAnnotations": {
    "runbook_url": "https://example.com/runbooks/disk"
  },
  "externalURL": "https://grafana.example.com/",
  "title": "[FIRING:1] DiskFull",
  "state": "alerting",
  "message": "Grafana notification",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "DiskFull",
        "severity": "critical",
        "instance": "host1",
        "grafana_folder": "Infrastructure",
        "__alert_rule_uid__": "disk-full-rule"
      },
      "annotations": {
        "summary": "Disk is full",
        "description": "/var is 95% full"
      },
      "startsAt": "2026-06-21T10:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "https://grafana.example.com/alerting/grafana/disk-full-rule/view",
      "fingerprint": "grafana-disk-full-host1",
      "silenceURL": "https://grafana.example.com/alerting/silence/new",
      "dashboardURL": "https://grafana.example.com/d/system-overview",
      "panelURL": "https://grafana.example.com/d/system-overview?viewPanel=12",
      "values": {
        "A": 95
      },
      "valueString": "[ var='A' value=95 ]"
    }
  ]
}
```

## Ручной тест

```bash
curl -X POST \
  "https://incidentrelay.example.com/api/integrations/grafana" \
  -H "Authorization: Bearer ROUTE_INTAKE_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @grafana-payload.json
```

Успешный ответ содержит по одному результату на каждый объект в массиве `alerts` Grafana.

```json
[
  {
    "created": true,
    "alert_id": 123,
    "group_id": 45,
    "status": "firing",
    "team_id": 2,
    "team_slug": "sre",
    "route_id": 7,
    "routing_error": null,
    "trace_id": "..."
  }
]
```

## HTTP-ответы

| Статус | Значение |
|---|---|
| `200` | Все экземпляры алертов обработаны успешно |
| `202` | Обработка принята, но не завершена полностью синхронно |
| `207` | Уведомление содержит смешанные результаты обработки |
| `400` | Некорректная полезная нагрузка или сбой маршрутизации |
| `401` | Токен приёма маршрута отсутствует или недействителен |

При сбое маршрутизации ответ включает `trace_id`. Администратор может использовать трассировку объяснения алерта для проверки вычисления матчеров и точной причины сбоя маршрутизации.

## Устранение неполадок

### Требуется токен приёма маршрута

Grafana не отправила заголовок авторизации.

Проверьте:

```text
Authentication Header Scheme: Bearer
Authentication Header Credentials: <route-intake-token>
```

Не добавляйте слово `Bearer` в поле учётных данных, когда схема настроена отдельно.

### Алерт не сопоставился ни с одним активным маршрутом

Проверьте, что:

- маршрут активен;
- источник маршрута — `grafana`;
- токен принадлежит этому маршруту;
- входящие метки удовлетворяют каждому настроенному матчеру;
- команда маршрута активна и доступна.

Используйте возвращённый `trace_id` для проверки вычисления маршрута.

### Уведомления resolved не приходят

Убедитесь, что в точке контакта вебхука Grafana не включён параметр **Disable resolved message**.

IncidentRelay использует статус каждого элемента в массиве `alerts`, а не только статус верхнего уровня.

### Алерты дублируются

Проверьте, что Grafana отправляет стабильный `fingerprint`. Когда fingerprint недоступен, сохраняйте UID правила и метки маршрутизации стабильными между уведомлениями firing и resolved.

Не включайте изменчивые значения в метки, используемые для идентификации экземпляра алерта.

### Ссылки на дашборд или панель пусты

Grafana включает ссылки на дашборд и панель только тогда, когда правило алерта связано с соответствующими метаданными дашборда и панели. URL правила алерта остаётся доступным через `generatorURL`.

### Тестовое уведомление не соответствует production-маршрутизации

Метки тестовой полезной нагрузки Grafana могут отличаться от реальных меток правил алертов. Сравните полученные метки в трассировке объяснения с матчерами маршрута.

## Безопасность

- Используйте HTTPS для эндпоинта-вебхука.
- Храните токены приёма маршрутов как секреты.
- Используйте отдельный токен маршрута для каждой интеграции или границы доверия.
- Немедленно ротируйте токен, если он был раскрыт.
- Не помещайте токен в URL.
- Ограничивайте матчеры маршрута, чтобы утёкший токен не мог маршрутизировать посторонние алерты.
