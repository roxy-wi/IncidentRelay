# Cloud.ru Advanced: Cloud Eye через SMN

IncidentRelay принимает аварийные сигналы Cloud.ru Advanced Cloud Eye через Simple Message Notification (SMN).

## Архитектура

```text
Cloud Eye -> SMN Topic -> подписанный HTTP/HTTPS webhook -> IncidentRelay Route
```

В Cloud Eye включите уведомления как для **Generated alarm**, так и для **Cleared alarm**, чтобы IncidentRelay получил полный lifecycle `firing -> resolved`.

## Настройка IncidentRelay

1. Откройте **Routes**.
2. Создайте маршрут с source **Cloud.ru Cloud Eye / SMN**.
3. Выберите team, параметры уведомлений и при необходимости default service.
4. Укажите точный **SMN Topic URN**, который используется Cloud Eye.
5. Сохраните маршрут.
6. Скопируйте созданный webhook URL:

```text
https://incidentrelay.example/api/integrations/cloud-ru/<route_id>
```

Bearer token для SMN не нужен. IncidentRelay проверяет SMN V1 signature, сертификат Cloud.ru и точное совпадение Topic URN.

## Настройка Cloud.ru

1. Создайте SMN topic в Cloud.ru Advanced.
2. Добавьте HTTP/HTTPS subscription с webhook URL IncidentRelay.
3. IncidentRelay проверит подпись и автоматически подтвердит subscription.
4. Создайте или измените alarm rule в Cloud Eye.
5. Включите **Alarm Notification** и выберите SMN topic.
6. Включите **Generated alarm** и **Cleared alarm**.

## Нормализация

`alarm` преобразуется в `firing`; `ok`, `cleared` и `resolved` — в `resolved`.

Приоритеты Cloud.ru `1/2/3/4` (Critical/Major/Minor/Informational) преобразуются соответственно в `critical/high/warning/info`.

`alarm_id` используется как стабильный dedup key, поэтому сообщение о восстановлении закрывает существующий alert.

В labels доступны `cloud_ru_alarm_id`, `cloud_ru_alarm_name`, `cloud_ru_alarm_status`, `cloud_ru_alarm_level`, `cloud_ru_namespace`, `cloud_ru_metric_name`, идентификаторы SMN и dimensions, например `cloud_ru_dimension_instance_id`.

## Безопасность

IncidentRelay проверяет source и состояние Route, точный Topic URN, заголовки `X-SMN-MESSAGE-*`, RSA-подпись SMN V1 и срок действия сертификата. URL сертификата и подтверждения подписки должны использовать HTTPS и домен Cloud.ru; redirects отключены.
