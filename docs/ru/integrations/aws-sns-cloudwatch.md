# Интеграция с AWS SNS и CloudWatch

IncidentRelay может принимать подписанные сообщения Amazon SNS и уведомления об алармах CloudWatch через отдельную входящую интеграцию. Сообщения принимаются только после проверки подписи SNS, URL сертификата подписи, источника маршрута, состояния маршрута и точного соответствия Topic ARN.

## Эндпоинт

```text
POST /api/integrations/aws-sns/{route_id}
```

Пример:

```text
https://incidentrelay.example.com/api/integrations/aws-sns/17
```

Этот эндпоинт не использует bearer-токен приёма маршрута. Amazon SNS аутентифицирует запросы с помощью подписи сообщения, при этом IncidentRelay дополнительно требует, чтобы `TopicArn` точно совпадал со значением, сохранённым в маршруте.

## Создание маршрута IncidentRelay

1. Откройте **Routes**.
2. Создайте маршрут.
3. Выберите **AWS SNS / CloudWatch** в качестве источника.
4. Выберите команду-владельца.
5. Введите точный SNS Topic ARN.
6. Настройте матчеры и группировку.
7. Выберите политику ротации или эскалации.
8. Включите и сохраните маршрут.
9. Откройте детали маршрута и скопируйте URL вебхука SNS.

Пример Topic ARN:

```text
arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts
```

Рекомендуемая группировка:

```json
[
  "cloudwatch_alarm_arn"
]
```

Это удерживает все изменения состояния одного аларма CloudWatch в одной группе IncidentRelay.

## Создание подписки SNS

В Amazon SNS:

1. Откройте топик, ARN которого настроен в маршруте.
2. Создайте подписку.
3. Выберите **HTTPS** в качестве протокола.
4. Укажите в качестве эндпоинта URL вебхука IncidentRelay.
5. Создайте подписку.

Amazon SNS отправляет подписанное сообщение `SubscriptionConfirmation`. IncidentRelay проверяет его и подтверждает подписку автоматически.

## Настройка аларма CloudWatch

Привяжите топик SNS к действиям уведомлений аларма CloudWatch. Для полного жизненного цикла отправляйте уведомления как минимум для:

```text
ALARM
OK
```

`ALARM` создаёт или обновляет активный алерт IncidentRelay. `OK` разрешает существующий алерт, поскольку оба уведомления используют один и тот же ARN аларма CloudWatch.

`INSUFFICIENT_DATA` трактуется как активный алерт с важностью warning.


## Пример настройки через AWS CLI

Ту же конфигурацию можно создать через AWS CLI. Сначала подпишите endpoint маршрута IncidentRelay на SNS topic:

```bash
TOPIC_ARN='arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts'

aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol https \
  --notification-endpoint 'https://incidentrelay.example.com/api/integrations/aws-sns/17'
```

IncidentRelay проверяет подписанный `SubscriptionConfirmation` и подтверждает подписку автоматически.

Затем создайте или обновите CloudWatch alarm и отправляйте как alarm, так и recovery actions в один и тот же SNS topic:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name HighCPU \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-0123456789abcdef0 \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 90 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN" \
  --ok-actions "$TOPIC_ARN"
```

Использование одного topic одновременно в `--alarm-actions` и `--ok-actions` даёт IncidentRelay полный lifecycle firing → resolved.

## Сопоставление состояний CloudWatch

| Состояние CloudWatch | Статус IncidentRelay | Важность по умолчанию |
|---|---|---|
| `ALARM` | `firing` | `critical` |
| `INSUFFICIENT_DATA` | `firing` | `warning` |
| `OK` | `resolved` | `info` |

Атрибут сообщения SNS `severity` переопределяет важность по умолчанию.

## Дедупликация

IncidentRelay использует `AlarmArn` одновременно как внешний идентификатор и ключ дедупликации.

Пример:

```text
arn:aws:cloudwatch:eu-west-1:123456789012:alarm:HighCPU
```

Один и тот же ARN должен присутствовать в уведомлениях `ALARM` и `OK`, чтобы существующий алерт обновлялся, а не дублировался.

## Нормализованные метки

Общие метки включают:

| Метка IncidentRelay | Источник |
|---|---|
| `alertname` | `AlarmName` |
| `severity` | атрибут SNS или сопоставление состояний |
| `aws_service` | `cloudwatch` |
| `aws_account_id` | `AWSAccountId` |
| `aws_region` | `Region` |
| `cloudwatch_alarm_arn` | `AlarmArn` |
| `cloudwatch_state` | `NewStateValue` |
| `cloudwatch_previous_state` | `OldStateValue` |
| `cloudwatch_metric_name` | `Trigger.MetricName` |
| `cloudwatch_namespace` | `Trigger.Namespace` |
| `cloudwatch_statistic` | `Trigger.Statistic` |
| `cloudwatch_unit` | `Trigger.Unit` |
| `cloudwatch_period` | `Trigger.Period` |
| `cloudwatch_evaluation_periods` | `Trigger.EvaluationPeriods` |
| `cloudwatch_datapoints_to_alarm` | `Trigger.DatapointsToAlarm` |
| `cloudwatch_comparison_operator` | `Trigger.ComparisonOperator` |
| `cloudwatch_threshold` | `Trigger.Threshold` |
| `cloudwatch_treat_missing_data` | `Trigger.TreatMissingData` |
| `sns_topic_arn` | SNS `TopicArn` |
| `sns_message_id` | SNS `MessageId` |

Измерения CloudWatch используют префикс `dimension_`. Например:

```text
dimension_instanceid=i-0123456789abcdef0
```

## Атрибуты сообщения SNS

Строковые атрибуты сообщения SNS преобразуются в метки.

```json
{
  "team": {
    "Type": "String",
    "Value": "sre"
  },
  "environment": {
    "Type": "String",
    "Value": "production"
  },
  "severity": {
    "Type": "String",
    "Value": "critical"
  }
}
```

Они становятся:

```text
team=sre
environment=production
severity=critical
```

Атрибуты `team` и `oncall_team` могут служить подсказкой команды, но приоритет остаётся за сопоставлением маршрута.

## Примеры матчеров маршрута

Только production:

```json
{
  "environment": "production"
}
```

Один аккаунт AWS:

```json
{
  "aws_account_id": "123456789012"
}
```

Алармы по CPU для EC2:

```json
{
  "cloudwatch_namespace": "AWS/EC2",
  "cloudwatch_metric_name": "CPUUtilization"
}
```

Один инстанс EC2:

```json
{
  "dimension_instanceid": "i-0123456789abcdef0"
}
```

Должны совпадать все настроенные матчеры.

## Пример уведомления SNS

Поле `Message` содержит полезную нагрузку аларма CloudWatch, закодированную в JSON.

```json
{
  "Type": "Notification",
  "MessageId": "sns-message-1",
  "TopicArn": "arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts",
  "Subject": "ALARM: HighCPU",
  "Message": "{\"AlarmName\":\"HighCPU\",\"AWSAccountId\":\"123456789012\",\"NewStateValue\":\"ALARM\",\"NewStateReason\":\"Threshold crossed\",\"Region\":\"EU (Ireland)\",\"AlarmArn\":\"arn:aws:cloudwatch:eu-west-1:123456789012:alarm:HighCPU\",\"OldStateValue\":\"OK\"}",
  "Timestamp": "2026-06-21T10:00:01.000Z",
  "SignatureVersion": "2",
  "Signature": "base64-signature",
  "SigningCertURL": "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-example.pem"
}
```

Полезная нагрузка, созданная вручную с подписью-заглушкой, отклоняется. Подпись должна быть сгенерирована Amazon SNS.

## Составные алармы

Полезная нагрузка составного аларма может содержать:

- `AlarmRule`;
- `TriggeringChildren`.

IncidentRelay сохраняет эти значения в аннотациях и сохраняет полную полезную нагрузку CloudWatch. Дедупликация по-прежнему использует ARN аларма.

## Обобщённые уведомления SNS

Когда `Message` не распознаётся как аларм CloudWatch, IncidentRelay создаёт обобщённый алерт SNS, используя:

- `Subject` в качестве заголовка;
- `Message` в качестве сообщения;
- `MessageId` в качестве внешнего идентификатора и ключа дедупликации;
- строковые атрибуты сообщения в качестве меток;
- `warning` в качестве важности по умолчанию;
- `firing` в качестве статуса.

## Сохранённая полезная нагрузка

IncidentRelay сохраняет:

```text
payload.sns
payload.cloudwatch
```

Подпись SNS удаляется перед сохранением полезной нагрузки. Остальная часть конверта SNS и тело аларма CloudWatch остаются доступными для диагностики и аудита.

## Проверка подписи

Перед принятием запроса IncidentRelay проверяет:

1. существование маршрута;
2. что источник маршрута — `aws_sns`;
3. что маршрут, команда и группа активны;
4. что конверт SNS корректен;
5. что опциональные заголовки SNS совпадают с телом JSON;
6. что `TopicArn` точно совпадает с конфигурацией маршрута;
7. что `SigningCertURL` использует HTTPS;
8. что хост и путь сертификата принадлежат Amazon SNS;
9. что сертификат в настоящий момент действителен;
10. что RSA-подпись соответствует канонической строке подписи SNS.

Алгоритмы подписи:

| Версия подписи | Дайджест |
|---|---|
| `1` | SHA-1 |
| `2` | SHA-256 |

## Ответы на подписку

Успешное подтверждение:

```json
{
  "status": "confirmed",
  "message_id": "sns-confirmation-1",
  "topic_arn": "arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts"
}
```

Подтверждение отписки:

```json
{
  "status": "unsubscribed",
  "message_id": "sns-confirmation-2",
  "topic_arn": "arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts"
}
```

## Ответ при успешном уведомлении

```json
[
  {
    "created": true,
    "alert_id": 123,
    "group_id": 45,
    "status": "firing",
    "team_id": 2,
    "team_slug": "sre",
    "route_id": 17,
    "routing_error": null,
    "trace_id": "..."
  }
]
```

## HTTP-ответы

| Статус | Значение |
|---|---|
| `200` | Уведомление обработано или состояние подписки подтверждено |
| `202` | Обработка принята, но не завершена полностью синхронно |
| `207` | Смешанные результаты приёма |
| `400` | Некорректный конверт, заголовки, источник маршрута или данные подтверждения |
| `403` | Не пройдена проверка подписи, Topic ARN, маршрута, команды или группы |
| `404` | Маршрут не найден |
| `502` | Не удалось загрузить сертификат подписи или подтвердить подписку |

## Устранение неполадок

### Подписка остаётся в состоянии pending

Проверьте, что:

- эндпоинт IncidentRelay публично доступен через HTTPS;
- источник маршрута — `aws_sns`;
- маршрут активен;
- настроенный Topic ARN точно совпадает с топиком SNS;
- IncidentRelay может обращаться к URL сертификата и подтверждения Amazon SNS;
- обратный прокси передаёт тела POST без изменений.

### Несоответствие Topic ARN

Проверьте раздел (partition) AWS, регион, ID аккаунта, имя топика и опциональный суффикс `.fifo`. Сравнение точное.

### Не удалось проверить подпись

Не редактируйте и не воспроизводите вручную подписанное тело SNS. Любое изменение подписанного поля делает подпись недействительной.

Также проверьте:

- исходящий доступ по HTTPS из IncidentRelay;
- синхронизацию системных часов;
- что тело не переписывается прокси;
- что сообщение пришло из настроенного топика.

### Аларм не разрешается

Убедитесь, что CloudWatch отправляет уведомление при переходе аларма в состояние `OK`. Сообщения `ALARM` и `OK` должны содержать один и тот же `AlarmArn`.

### Алерт не сопоставился с маршрутом

Используйте возвращённый `trace_id` для проверки маршрутизации. Проверьте состояние маршрута, состояние команды, цель назначения и каждый настроенный матчер.

### Несколько алармов группируются вместе

Используйте:

```json
[
  "cloudwatch_alarm_arn"
]
```

в качестве конфигурации группировки маршрута.

## Рекомендации по безопасности

- Используйте только HTTPS.
- Используйте отдельный топик SNS для каждой среды или границы доверия.
- Настройте точный Topic ARN на каждом маршруте.
- Не отключайте проверку URL сертификата.
- Не принимайте редиректы при загрузке сертификатов или подтверждении подписок.
- Держите системное время IncidentRelay синхронизированным.
- Проверяйте трассировки маршрутизации и журналы после отклонённых запросов.
