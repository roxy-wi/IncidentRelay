---
title: Провайдерский API
description: Как написать пользовательский голосовой провайдер IncidentRelay
---

# Провайдерский API

Каждый модуль провайдера должен определять класс с именем `Provider`.

Класс должен наследоваться от:

```python
app.notifiers.voice.base.BaseVoiceProvider
```

## Минимальный провайдер

```python
from app.notifiers.voice.base import (
    BaseVoiceProvider,
    VoiceCallRequest,
    VoiceCallResult,
    VoiceProviderCapabilities,
)


class Provider(BaseVoiceProvider):
    """Minimal custom voice provider."""

    name = "example"

    capabilities = VoiceProviderCapabilities(
        tts=True,
        status_callback=False,
        dtmf_callback=False,
        status_polling=False,
    )

    def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Place a voice call."""

        print(f"Calling {request.phone}: {request.text}")

        return VoiceCallResult(
            call_id="example-call-id",
            status="queued",
            raw={"provider": self.name},
        )
```

## Методы провайдера

Провайдер может реализовать:

```python
place_call()
parse_callback()
get_call_status()
validate_config()
```

Обязателен только `place_call()`.

Методы колбэков и опроса необязательны и зависят от того, что поддерживает ваш провайдер.

## BaseVoiceProvider

```python
class BaseVoiceProvider:
    name = "base"

    capabilities = VoiceProviderCapabilities()

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> None:
        """Validate provider-specific configuration."""

    def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Place a voice call."""

        raise NotImplementedError

    def parse_callback(
        self,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        raw_body: bytes | None = None,
        query_args: dict[str, Any] | None = None,
    ) -> list[VoiceCallCallbackEvent]:
        """Parse provider webhook callback."""

        return []

    def get_call_status(self, call_id: str) -> VoiceCallResult:
        """Return current call status."""

        raise NotImplementedError
```

## Возможности

Каждый провайдер должен объявлять свои возможности.

```python
from app.notifiers.voice.base import VoiceProviderCapabilities


class Provider(BaseVoiceProvider):
    name = "mango"

    capabilities = VoiceProviderCapabilities(
        tts=True,
        status_callback=True,
        dtmf_callback=True,
        status_polling=False,
    )
```

### tts

Провайдер может принимать текст и воспроизводить его во время вызова.

### status_callback

Провайдер может отправлять колбэки вебхуков с изменениями статуса вызова.

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

### dtmf_callback

Провайдер может отправлять колбэки вебхуков, когда пользователь нажимает кнопки телефонной клавиатуры.

Пример:

```text
1 -> acknowledge
2 -> resolve
```

### status_polling

Провайдер может возвращать статус вызова через запрос к API.

Это полезно, когда провайдер не поддерживает колбэки.

## VoiceCallRequest

`place_call()` получает один `VoiceCallRequest`.

```python
def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
    ...
```

### Поля

| Поле | Описание |
|---|---|
| `request.phone` | Целевой номер телефона |
| `request.text` | Текст, который должен быть произнесён во время вызова |
| `request.alert_id` | Идентификатор алерта IncidentRelay |
| `request.event_type` | Тип события уведомления: `notification`, `reminder`, `escalation`, `test` |
| `request.callback_url` | URL колбэка для событий статуса и DTMF |
| `request.callback_secret` | Секрет колбэка, используемый в URL колбэка |
| `request.severity` | Уровень важности алерта |
| `request.title` | Заголовок алерта |
| `request.message` | Сообщение алерта |
| `request.assignee` | Читаемое имя ответственного |
| `request.team` | Slug команды |
| `request.action_hints` | Рекомендуемые действия с клавиатуры |
| `request.metadata` | Дополнительные метаданные IncidentRelay |

Пример `action_hints`:

```python
{
    "1": "acknowledge",
    "2": "resolve",
}
```

Пример `metadata`:

```python
{
    "channel_id": 1,
    "channel_name": "infra-voice-critical",
    "channel_type": "voice_call",
}
```

## VoiceCallResult

`place_call()` и `get_call_status()` должны возвращать `VoiceCallResult`.

```python
return VoiceCallResult(
    call_id="abc-123",
    status="queued",
    raw=response_data,
)
```

### call_id

Внешний идентификатор вызова, возвращаемый провайдером.

IncidentRelay сохраняет его как `external_message_id`.

Этот идентификатор позже используется для сопоставления колбэков провайдера с исходным уведомлением об алерте.

### status

Нормализованный статус провайдера.

Рекомендуемые значения:

```text
queued
ringing
answered
completed
failed
busy
no_answer
cancelled
logged
unknown
```

### raw

Исходный ответ провайдера или полезная отладочная информация.

Не помещайте секреты в `raw`.

## VoiceCallCallbackEvent

`parse_callback()` должен возвращать список объектов `VoiceCallCallbackEvent`.

```python
return [
    VoiceCallCallbackEvent(
        call_id="abc-123",
        event_type="dtmf",
        status="answered",
        digit="1",
        raw=payload,
    )
]
```

### Поля

| Поле | Описание |
|---|---|
| `call_id` | Внешний идентификатор вызова провайдера |
| `event_type` | Нормализованный тип события: `status`, `dtmf`, `error` |
| `status` | Статус вызова |
| `digit` | Цифра DTMF, нажатая получателем вызова |
| `action` | Необязательное нормализованное действие IncidentRelay |
| `alert_id` | Необязательный идентификатор алерта |
| `message` | Необязательное читаемое сообщение колбэка |
| `raw` | Исходная полезная нагрузка колбэка провайдера |

Поддерживаемые действия:

```text
acknowledge
resolve
```
