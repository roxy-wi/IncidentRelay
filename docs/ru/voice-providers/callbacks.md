---
title: Колбэки и DTMF
description: Колбэки голосового провайдера, статусы и действия с клавиатуры
---

# Колбэки и DTMF

IncidentRelay может принимать колбэки провайдера для:

- изменений статуса вызова;
- ввода с телефонной клавиатуры DTMF;
- ошибок провайдера.

## URL колбэка

Когда IncidentRelay создаёт вызов, он передаёт провайдеру `callback_url`.

Пример:

```text
https://incidentrelay.example.com/api/integrations/voice/callback/12/change-me-channel-secret
```

Формат URL:

```text
/api/integrations/voice/callback/{channel_id}/{secret}
```

## Поток колбэков

Провайдер должен отправлять события вызова на URL колбэка.

IncidentRelay выполнит:

```text
1. Validate callback secret.
2. Load the globally configured voice provider.
3. Pass raw callback payload to provider.parse_callback().
4. Find notification by provider call_id.
5. Store callback status and payload.
6. Write callback event history.
7. Apply DTMF action if configured.
```

## Колбэк статуса

Пример колбэка провайдера:

```json
{
  "call_id": "abc-123",
  "event_type": "status",
  "status": "answered"
}
```

Нормализация на стороне провайдера:

```python
return [
    VoiceCallCallbackEvent(
        call_id=payload["call_id"],
        event_type="status",
        status=payload["status"],
        raw=payload,
    )
]
```

Рекомендуемые статусы:

```text
queued
ringing
answered
completed
failed
busy
no_answer
cancelled
unknown
```

IncidentRelay сохраняет последний статус в записи уведомления, а также сохраняет историю колбэков.

## Колбэк DTMF

DTMF означает ввод с телефонной клавиатуры.

Отображение по умолчанию:

```json
{
  "1": "acknowledge",
  "2": "resolve"
}
```

Пример произносимого сообщения:

```text
IncidentRelay alert 123.
Disk is full.
Severity critical.
Press 1 to acknowledge.
Press 2 to resolve.
```

Если пользователь нажимает `1`, провайдер отправляет:

```json
{
  "call_id": "abc-123",
  "event_type": "dtmf",
  "digit": "1"
}
```

IncidentRelay сопоставляет это с:

```text
acknowledge
```

Если пользователь нажимает `2`, IncidentRelay сопоставляет это с:

```text
resolve
```

Провайдер также может отправить нормализованное действие напрямую:

```json
{
  "call_id": "abc-123",
  "event_type": "dtmf",
  "action": "acknowledge"
}
```

В этом случае IncidentRelay не нужно сопоставлять цифру.

## Колбэк ошибки

Провайдеры могут отправлять события об ошибках.

```json
{
  "call_id": "abc-123",
  "event_type": "error",
  "status": "failed",
  "message": "Insufficient balance"
}
```

Нормализация на стороне провайдера:

```python
return [
    VoiceCallCallbackEvent(
        call_id=payload["call_id"],
        event_type="error",
        status="failed",
        message=payload.get("message"),
        raw=payload,
    )
]
```

## Подписи колбэков, специфичные для провайдера

Некоторые провайдеры подписывают колбэки вебхуков.

`parse_callback()` получает:

```python
payload
headers
raw_body
query_args
```

Используйте `headers` и `raw_body` для проверки подписей провайдера.

Пример:

```python
def parse_callback(self, payload, headers=None, raw_body=None, query_args=None):
    signature = headers.get("X-Provider-Signature") if headers else None

    if not self._is_valid_signature(raw_body or b"", signature):
        raise RuntimeError("invalid provider callback signature")

    ...
```

IncidentRelay проверяет свой собственный секрет колбэка перед вызовом `parse_callback()`.

Проверка подписи, специфичной для провайдера, необязательна, но рекомендуется, когда провайдер её поддерживает.

## Опрос статуса вызова

Некоторые провайдеры не поддерживают колбэки.

В этом случае провайдер может реализовать:

```python
def get_call_status(self, call_id: str) -> VoiceCallResult:
    ...
```

Пример:

```python
def get_call_status(self, call_id: str) -> VoiceCallResult:
    response = requests.get(
        f"{self.config['api_url'].rstrip('/')}/calls/{call_id}",
        headers={
            "Authorization": f"Bearer {self.config['api_token']}",
        },
        timeout=int(self.config.get("timeout", 10)),
    )
    response.raise_for_status()

    data = response.json() if response.content else {}

    return VoiceCallResult(
        call_id=call_id,
        status=str(data.get("status") or "unknown"),
        raw=data,
    )
```

Установите возможность:

```python
capabilities = VoiceProviderCapabilities(
    tts=True,
    status_callback=False,
    dtmf_callback=False,
    status_polling=True,
)
```
