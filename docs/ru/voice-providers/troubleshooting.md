---
title: Устранение неполадок голосового провайдера
description: Распространённые проблемы пользовательских голосовых провайдеров
---

# Устранение неполадок голосового провайдера

## Провайдер не найден

Пример ошибки:

```text
voice provider not found: mango
```

Проверьте:

```text
- File exists: /usr/local/lib/incidentrelay/voice_providers/mango.py
- Channel config has: "provider": "mango"
- File name contains only letters, numbers and underscore
- IncidentRelay was restarted after adding the file
```

## Отсутствует класс провайдера

Пример ошибки:

```text
voice provider mango must define Provider(BaseVoiceProvider)
```

Проверьте, что ваш модуль содержит:

```python
class Provider(BaseVoiceProvider):
    ...
```

Имя класса должно быть в точности:

```text
Provider
```

## Отсутствует поле конфигурации

Пример ошибки:

```text
mango config requires: api_url, api_token
```

Проверьте `provider_config` в конфигурации канала.

## Токен API пуст

Если вы используете:

```json
"api_token": "${VOICE_API_TOKEN}"
```

Проверьте, что переменная окружения существует для процесса IncidentRelay.

Для systemd:

```bash
sudo systemctl show incidentrelay --property=Environment
```

Или проверьте свой service unit / файл окружения.

## Вызовы не отправляются по реальным алертам

Проверьте:

```text
- Alert status is firing.
- Alert severity is listed in notify_on_severities.
- Alert has an assignee with phone number.
- Channel is enabled.
- Route points to the voice channel.
```

## Колбэк отклонён

Проверьте:

```text
- Callback URL contains the correct channel_id.
- Callback URL contains the correct callback secret.
- Channel type is voice_call.
- Channel config has the expected provider.
- Provider sends JSON or form data supported by parse_callback().
```

## DTMF не подтверждает и не разрешает алерт

Проверьте:

```text
- Provider sends event_type=dtmf or equivalent data that parse_callback() maps to dtmf.
- Provider sends digit.
- Channel config dtmf_actions contains this digit.
- The digit maps to acknowledge or resolve.
- call_id matches the original VoiceCallResult.call_id.
```

## Уведомление для колбэка не найдено

Проверьте:

```text
- Provider returned call_id from place_call().
- Provider sends the same call_id in callbacks.
- IncidentRelay stored external_message_id for the notification.
- Callback is sent to the same channel_id that created the call.
```

## Запрос провайдера зависает

Проверьте:

```text
- All HTTP requests have timeouts.
- Provider API endpoint is reachable from IncidentRelay.
- DNS resolution works.
- Firewall allows outbound provider traffic.
```

Хорошо:

```python
requests.post(url, json=payload, timeout=10)
```

Плохо:

```python
requests.post(url, json=payload)
```

## Контрольный список тестирования

Перед включением провайдера в продакшене:

```text
1. Create a test voice channel.
2. Set test_phone.
3. Configure only one test severity, for example critical.
4. Trigger a test notification.
5. Check IncidentRelay logs.
6. Check provider-side logs or dashboard.
7. Confirm that call_id is returned.
8. Confirm that call status callbacks are received.
9. Confirm that DTMF callback with digit 1 acknowledges the alert.
10. Confirm that DTMF callback with digit 2 resolves the alert.
11. Confirm that provider errors are visible in IncidentRelay logs.
12. Confirm that secrets and full phone numbers are not logged.
13. Enable the provider for real alert routes.
```
